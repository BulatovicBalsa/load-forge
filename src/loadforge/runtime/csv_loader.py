"""
CSV credentials loader for multi-user load testing.
"""
import csv
from pathlib import Path
from typing import Any


def load_user_data_from_csv(csv_path: str, base_dir: Path) -> list[dict[str, str]]:
    path = Path(csv_path.strip().strip('"'))
    if not path.is_absolute():
        path = base_dir / path
    
    if not path.exists():
        raise FileNotFoundError(
            f"User data CSV file not found: {path}\n"
            f"Looking in: {base_dir}"
        )
    
    users = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        if not reader.fieldnames:
            raise ValueError(f"CSV file has no header row: {path}")
        
        for row_num, row in enumerate(reader, start=2):
            cleaned_row = {key: value.strip() for key, value in row.items()}
            
            empty_fields = [key for key, value in cleaned_row.items() if not value]
            if empty_fields:
                raise ValueError(
                    f"Empty value(s) in CSV row {row_num} for column(s): {', '.join(empty_fields)}\n"
                    f"File: {path}"
                )
            
            users.append(cleaned_row)
    
    if not users:
        raise ValueError(f"No user data found in CSV file: {path}")
    
    return users
