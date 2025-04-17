from src.config.config import global_config
from src.do_tool.tool_can_use.base_tool import BaseTool
from src.common.logger import get_module_logger
from typing import Dict, Any, Optional, Tuple
import os
import re
import asyncio
from tavily import TavilyClient

from src.plugins.models.utils_model import LLMRequest

logger = get_module_logger("web_search_tool")


class WebSearchTool(BaseTool):
    """综合网络搜索工具（集成搜索判断与结果处理）"""

    # name = "web_search"
    name = "search_knowledge_web"
    description = "在线获取准确的参考信息"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "需要分析的原始消息"},
            "max_results": {"type": "number", "description": "最大返回结果数（1-5）", "default": 3}
        },
        "required": ["text"],
    }

    def __init__(self):
        super().__init__()
        # 初始化搜索客户端
        self.tavily_api_key = os.environ.get("SEARCH_API_KEY", "")
        self.tavily_client = TavilyClient(self.tavily_api_key) if self.tavily_api_key else None

        # 初始化LLM模型
        self.judge_model = LLMRequest(
            model=global_config.llm_heartflow,
            temperature=0.2,
            max_tokens=100,
            request_type="search_judge"
        )
        self.summary_model = LLMRequest(
            model=global_config.llm_summary_by_topic,
            temperature=0.3,
            max_tokens=1500,
            request_type="search_summary"
        )

        # 加载配置
        self.search_probability = 0.7
        self.max_search_results = 4

    async def execute(self, function_args: Dict[str, Any], message_txt: str = "") -> Dict[str, Any]:
        """执行智能搜索流程"""
        try:
            if not self.tavily_client:
                return {"name": self.name, "content": "缺少搜索工具"}
            # 参数解析
            text = function_args.get("text", message_txt)
            max_results = min(int(function_args.get("max_results", 3)), 5)
            logger.info(f"正在搜索: {text}，最多{max_results}个结果。")

            # 步骤1：搜索必要性判断
            keywords, topic = await self._search_judgement(text)
            logger.info(f"搜索关键词: {keywords}，话题: {topic}")
            # if not should_search or not self.tavily_client:
            #     return {"name": self.name, "content": "当前问题无需网络搜索"}

            # 步骤2：执行搜索
            raw_results = await self._perform_search(keywords, topic, max_results)
            if not raw_results:
                return {"name": self.name, "content": "未找到相关网络信息"}

            # 步骤3：结果处理与摘要
            processed_content = await self._process_results(keywords, topic, raw_results)
            return {"name": self.name, "content": processed_content}

        except Exception as e:
            logger.error(f"搜索流程异常: {str(e)}")
            return {"name": self.name, "content": f"网络搜索失败: {str(e)}"}

    async def _search_judgement(self, text: str) -> Tuple[str, str]:
        """智能搜索判断与关键词提取"""
        prompt = f"""【搜索判断任务】
        用户消息: "{text}"
        请按以下格式响应：
        搜索关键词：[简洁关键词]
        搜索主题：[news/finance/general]"""

        try:
            response, _, _ = await self.judge_model.generate_response(prompt)

            # 解析响应
            # score = 0.0
            keywords = text  # 默认值
            topic = "general"

            for line in response.split('\n'):
                if "搜索关键词：" in line:
                    keywords = line.split("：")[1].strip()
                elif "搜索主题：" in line:
                    topic = line.split("：")[1].strip().lower()

            return keywords, topic

        except Exception as e:
            logger.warning(f"搜索判断异常: {str(e)}")
            return text, "general"

    def _parse_score(self, text: str) -> float:
        """解析评分文本"""
        try:
            match = re.search(r"\d+\.?\d*", text)
            return min(max(float(match.group()), 0.0), 1.0) if match else 0.0
        except:
            return 0.0

    async def _perform_search(self, query: str, topic: str, max_results: int) -> Optional[list]:
        """执行Tavily搜索"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.tavily_client.search(
                    query=query,
                    topic=topic,
                    max_results=max_results
                )
            )
            return response.get("results", [])
        except Exception as e:
            logger.error(f"搜索执行失败: {str(e)}")
            return None

    async def _process_results(self, query: str, topic: str, results: list) -> str:
        """处理并摘要搜索结果"""
        # 构建原始内容
        raw_content = "\n\n".join([
            f"标题：{res.get('title', '')}\n内容：{res.get('content', '')}"
            for res in results
        ])

        # 生成摘要提示词
        prompt = f"""根据以下搜索结果，生成结构化的知识摘要：

        搜索主题：{topic}
        原始查询：{query}
        搜索结果：
        {raw_content}

        要求：
        1. 使用Markdown格式组织内容
        2. 保留关键数据、日期、名称
        3. 区分事实与观点
        4. 标注信息矛盾点（如有）
        """

        try:
            summary, _, _ = await self.summary_model.generate_response(prompt)
            return self._post_process_summary(summary)
        except Exception as e:
            logger.warning(f"摘要生成失败，返回原始结果: {str(e)}")
            return raw_content

    def _post_process_summary(self, text: str) -> str:
        """后处理摘要内容"""
        # 清理常见模型输出问题
        text = re.sub(r"^当然，.*?下面是我的摘要：", "", text)
        text = re.sub(r"\*\*摘要：\*\*", "", text)
        return "你缺少相关知识，于是搜索了网络，得到了如下信息：\n" + text.strip()