from src.do_tool.tool_can_use.base_tool import BaseTool
from src.common.logger import get_module_logger
from typing import Dict, Any
import math
import re

logger = get_module_logger("math_calculator_tool")


class MathCalculatorTool(BaseTool):
    """安全数学表达式计算工具"""

    name = "math_calculator"
    description = "解析并计算数学表达式，支持基本运算和常用函数"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "数学表达式（支持：+-*/^()、sin/cos/tan/log/sqrt/pow，常量pi/e）"
            }
        },
        "required": ["expression"],
    }
    base_pattern = re.compile(r"^[\d\s+\-*/^().!]+|(sin|cos|tan|log|ln|sqrt|pow)\s*\(|(pi|e)\b$")

    async def execute(self, function_args: Dict[str, Any], message_txt: str = "") -> Dict[str, Any]:
        """执行数学表达式计算"""
        try:
            expression = function_args.get("expression", "").strip()

            # 安全验证
            # if not self._validate_expression(expression):
            #     return {"name": self.name, "content": "表达式包含不安全内容"}

            # 预处理
            processed_expr = self._preprocess_expression(expression)

            # 安全计算环境
            safe_env = {
                "__builtins__": None,
                "math": math,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log10,  # 默认以10为底
                "ln": math.log,  # 自然对数
                "sqrt": math.sqrt,
                "pow": math.pow,
                "pi": math.pi,
                "e": math.e,
            }

            result = eval(processed_expr, {"__builtins__": None}, safe_env)
            return {"name": self.name, "content": f"计算结果：{result:.6f}".rstrip('0').rstrip('.')}

        except SyntaxError as e:
            logger.error(f"语法错误: {expression} -> {str(e)}")
            return {"name": self.name, "content": "表达式语法错误"}
        except ZeroDivisionError:
            return {"name": self.name, "content": "错误：除零操作"}
        except Exception as e:
            logger.error(f"计算错误: {expression} -> {str(e)}")
            return {"name": self.name, "content": f"计算失败：{str(e)}"}

    def _validate_expression(self, expr: str) -> bool:
        """多层安全验证"""
        # 1. 基础字符白名单
        if not self.base_pattern.match(expr, re.VERBOSE | re.IGNORECASE):
            return False

        # 2. 函数调用格式验证
        func_pattern = r"(sin|cos|tan|log|ln|sqrt|pow)\s*\("
        for match in re.finditer(func_pattern, expr, re.IGNORECASE):
            func_name = match.group(1).lower()
            # 检查函数参数数量
            if func_name in ["log", "pow"] and not self._validate_log_pow_args(expr, match.end()):
                return False

        # 3. 危险组合检查
        danger_patterns = [
            r"__",  # 禁止双下划线
            r";",  # 禁止分号
            r"\[", r"\]"  # 禁止列表操作
        ]
        return not any(re.search(p, expr) for p in danger_patterns)

    @staticmethod
    def _validate_log_pow_args(expr: str, start_pos: int) -> bool:
        """验证log/pow函数参数数量"""
        bracket_count = 1
        comma_count = 0
        for i in range(start_pos, len(expr)):
            char = expr[i]
            if char == '(':
                bracket_count += 1
            if char == ')':
                bracket_count -= 1
            if char == ',' and bracket_count == 1:
                comma_count += 1
            if bracket_count == 0:
                break

        # log允许1或2个参数，pow必须2个参数
        func_type = expr[start_pos - 3:start_pos].lower().strip('(')
        if func_type == 'log' and comma_count > 1:
            return False
        if func_type == 'pow' and comma_count != 1:
            return False
        return True

    @staticmethod
    def _preprocess_expression(expr: str) -> str:
        """表达式预处理"""
        expr = expr.replace('π', 'pi').replace(' ', '')
        # 统一运算符
        expr = expr.replace('^', '**').replace(' ', '')
        # 处理隐式乘法
        expr = re.sub(r'(?<=\d)(?=[a-z(])', '*', expr, flags=re.IGNORECASE)
        expr = re.sub(r'(?<=[)π])(?=\d)', '*', expr)
        # 转换自然对数
        expr = re.sub(r'ln\s*\(', 'math.log(', expr)
        # 处理百分号
        expr = re.sub(r'(\d+)%', r'(\1/100)', expr)
        return expr
