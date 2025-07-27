#!/usr/bin/env python
# run_tests.py - 项目测试运行器

import unittest
import os
import sys

def run_tests():
    # 添加项目根目录到系统路径
    project_root = os.path.abspath(os.path.dirname(__file__))
    sys.path.insert(0, project_root)
    
    # 发现并运行所有测试
    loader = unittest.TestLoader()
    start_dir = os.path.join(project_root, 'src', 'tests')
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回测试结果
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

