"""AI模块初始化"""
from typing import Type
from .macro_analyzer import MacroAnalyzer
from .report_generator import ReportGenerator
from .ai_client import AIClient

__all__: list[str] = ['MacroAnalyzer', 'ReportGenerator', 'AIClient']
