# src/validator.py
import ast
import os

def validate_python_files():
    error_count = 0
    for root, _, files in os.walk("src"):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r") as f:
                        ast.parse(f.read())
                    print(f"✅ {path} 语法验证通过")
                except SyntaxError as e:
                    error_count += 1
                    print(f"❌ {path} 语法错误: {e}")
    
    if error_count > 0:
        raise RuntimeError(f"发现 {error_count} 个语法错误，请修复后提交")
    
    print("所有文件语法验证通过")

if __name__ == "__main__":
    validate_python_files()
