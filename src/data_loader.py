
import logging
import os
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

def get_data_path(filename: str) -> Optional[str]:
    """
    获取数据文件在服务器上的绝对路径。
    优先检查 Render Disk，如果不存在，则检查项目内置的 data 目录。
    """
    # 路径一：Render 的持久化磁盘
    # 这是我们通过 SSH/SCP 手动上传文件的位置
    render_disk_path = f"/opt/render/project/persistent/{filename}"
    if os.path.exists(render_disk_path):
        logger.info(f"在 Render Disk 上找到数据文件: {render_disk_path}")
        return render_disk_path

    # 路径二：项目内置的 data 目录
    # 这是我们通过 Git 推送的文件的位置
    project_data_path = os.path.join(os.getcwd(), "data", filename)
    if os.path.exists(project_data_path):
        logger.info(f"在项目 data 目录中找到数据文件: {project_data_path}")
        return project_data_path
    
    logger.warning(f"⚠️ 无法在任何已知位置找到数据文件: {filename}")
    return None

def load_strategy_data(filename: str) -> Optional[pd.DataFrame]:
    """
    加载策略数据文件（Excel 或 CSV）。
    
    Args:
        filename (str): 要加载的文件名，例如 "btc_strategy.xlsx"。
        
    Returns:
        Optional[pd.DataFrame]: 如果成功，返回一个 Pandas DataFrame；否则返回 None。
    """
    logger.info(f"正在尝试加载策略数据文件: {filename}...")
    
    file_path = get_data_path(filename)
    
    if not file_path:
        return None # 如果文件路径都找不到，直接返回 None

    try:
        # 根据文件扩展名，选择不同的读取方式
        if filename.endswith('.xlsx'):
            # 使用 openpyxl 引擎读取 Excel 文件
            df = pd.read_excel(file_path, engine='openpyxl')
        elif filename.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            logger.error(f"不支持的文件格式: {filename}。只支持 .xlsx 和 .csv。")
            return None
            
        logger.info(f"✅ 成功加载并解析了 {len(df)} 行数据从 {filename}")
        return df

    except FileNotFoundError:
        logger.error(f"文件不存在: {file_path}")
        return None
    except Exception as e:
        logger.error(f"加载或解析文件 {filename} 时出错: {e}", exc_info=True)
        return None
