import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import reduce
from operator import and_, or_
from pathlib import Path

import pandas as pd
import typer

TRANSACTIONS_DIR = Path(__file__).parent.parent / "transactions"

_CONFIG_PATH = Path(__file__).parent.parent / "transactions_config.json"
_CONFIG = json.loads(_CONFIG_PATH.read_text())
IGNORE_PATTERNS = _CONFIG["ignore_patterns"]
RECATEGORIZE_PATTERNS = _CONFIG["recategorize_patterns"]


def save(data: bytes, filename: str) -> Path:
    """Сохранить данные транзакций в файл."""
    output_dir = TRANSACTIONS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = _parse_filename(filename)
    if parsed:
        start_date, _ = parsed
        year_folder = output_dir / str(start_date.year)
        month_folder = year_folder / f"{start_date.month:02d}"
        month_folder.mkdir(parents=True, exist_ok=True)
        dest = month_folder / filename
    else:
        dest = output_dir / filename
    dest.write_bytes(data)
    typer.secho(f"[✓] Файл сохранён: {dest.resolve()}", fg=typer.colors.GREEN)
    return dest


def range_exists(range_start: int, range_end: int) -> bool:
    """Проверить, существует ли диапазон транзакций."""
    if not TRANSACTIONS_DIR.exists():
        return False

    start_dt = datetime.fromtimestamp(range_start / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(range_end / 1000, tz=UTC)

    for file in TRANSACTIONS_DIR.rglob("*.xlsx"):
        parsed = _parse_filename(file.name)
        if parsed is None:
            continue
        file_start, file_end = parsed
        file_start = file_start.replace(tzinfo=UTC)
        file_end = file_end.replace(tzinfo=UTC)

        if file_start <= start_dt and end_dt <= file_end:
            return True

    return False


def load(year: int | None = None, month: int | None = None) -> pd.DataFrame:  # noqa: C901
    """Загрузить транзакции из файлов."""
    if not TRANSACTIONS_DIR.exists():
        raise ValueError(f"{TRANSACTIONS_DIR} does not exist")

    frames = []
    for file in TRANSACTIONS_DIR.rglob("*.xlsx"):
        if year is not None:
            year_str = f"/{year}/"
            if year_str not in str(file):
                continue
        if month is not None:
            month_str = f"/{month:02d}/"
            if month_str not in str(file):
                continue

        excel_file = pd.ExcelFile(file)
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(file, sheet_name=sheet_name)

            if df.empty:
                continue

            df.columns = df.columns.str.strip().str.lower()

            for col in df.select_dtypes(include="object").columns:
                df[col] = df[col].str.strip().str.lower()

            if "сумма операции" in df.columns:
                df["сумма операции"] = (
                    df["сумма операции"].astype(str).str.replace(",", ".", regex=False)
                )
                df["сумма операции"] = pd.to_numeric(
                    df["сумма операции"],
                    errors="coerce",
                )
            frames.append(df)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _process(df)


def _parse_filename(filename: str) -> tuple[datetime, datetime] | None:
    """Извлечь даты из имени файла операций."""
    match = re.match(r"Operations (.+?)-(.+?)\.xlsx?$", filename)
    if not match:
        return None
    start_str = match.group(1).strip()
    end_str = match.group(2).strip()
    try:
        start_date = datetime.strptime(start_str, "%a %b %d %Y").replace(tzinfo=UTC)
        end_date = datetime.strptime(end_str, "%a %b %d %Y").replace(tzinfo=UTC)
    except ValueError:
        return None
    return start_date, end_date


def _build_match_mask(df: pd.DataFrame, patterns: Iterable[dict]) -> pd.Series:
    """Построить маску для фильтрации по паттернам."""
    filters = []
    for pattern in patterns:
        conditions = [df[col] == value for col, value in pattern.items()]
        filters.append(reduce(and_, conditions))
    return reduce(or_, filters)


def _exclude_ignored(df: pd.DataFrame) -> pd.DataFrame:
    """Исключить игнорируемые транзакции."""
    if df.empty:
        return df
    df = df.copy()
    ignore_filter = _build_match_mask(df, IGNORE_PATTERNS)
    return df[~ignore_filter]


def _recategorize(df: pd.DataFrame) -> pd.DataFrame:
    """Перекатегоризировать транзакции."""
    if df.empty:
        return df
    df = df.copy()
    for new_category, patterns in RECATEGORIZE_PATTERNS.items():
        mask = _build_match_mask(df, patterns)
        df.loc[mask, "категория"] = new_category
    return df


def _process(df: pd.DataFrame) -> pd.DataFrame:
    """Обработать транзакции: исключить и перекатегоризировать."""
    df = _exclude_ignored(df)
    df = _recategorize(df)
    return df
