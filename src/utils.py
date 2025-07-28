import csv
from typing import List, Dict

def read_csv_to_dict(filepath: str) -> List[Dict]:
    """轻量级CSV读取器替代pandas"""
    with open(filepath, 'r') as f:
        return list(csv.DictReader(f))
        
def write_dict_to_csv(data: List[Dict], filepath: str):
    """轻量级CSV写入器替代pandas"""
    if not data:
        return
        
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
