import hashlib
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
import typer
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

MIN_ROWS_THRESHOLD = 2

WORKSHEET_NAME = "Транзакции"
CREDENTIALS_PATH = Path(__file__).parent.parent / ".gdrive_creds.json"
_SPREADSHEET_URL = (Path(__file__).parent.parent / ".gdrive_link").read_text().strip()


def filter_new(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    existing = _get_existing_hashes()

    df = df.copy()
    normalized = _normalize_df(df)
    df["_hash"] = normalized.apply(_compute_row_hash, axis=1)
    filtered = df[~df["_hash"].isin(existing)]

    return filtered.drop(columns=["_hash"])


def upload(df: pd.DataFrame) -> None:
    if df.empty:
        typer.echo("Нет новых транзакций для загрузки.")
        return
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS_PATH),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(_SPREADSHEET_URL)
    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME,
            rows=len(df) + 1,
            cols=len(df.columns),
        )

    df_upload = df.copy()
    for col in df_upload.select_dtypes(include=["datetime64", "datetime"]).columns:
        df_upload[col] = df_upload[col].astype(str)
    df_upload = df_upload.fillna("")
    df_upload = df_upload.map(lambda x: x.item() if hasattr(x, "item") else x)

    header_values = [col.title() for col in df.columns]
    existing_values = worksheet.get_all_values()
    first_row = existing_values[0] if existing_values else []

    if first_row == header_values:
        worksheet.append_rows(
            df_upload.to_numpy().tolist(),
            value_input_option=ValueInputOption.user_entered,
        )
    else:
        data = [header_values, *df_upload.to_numpy().tolist()]
        worksheet.update(data, value_input_option=ValueInputOption.user_entered)

    typer.secho(
        f"✓ Данные загружены в '{WORKSHEET_NAME}' ({len(df)} строк)",
        fg=typer.colors.GREEN,
    )


def _get_existing_hashes() -> set[str]:
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS_PATH),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(_SPREADSHEET_URL)

    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        return set()

    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < MIN_ROWS_THRESHOLD:
        return set()

    def is_numeric_row(row: list[str]) -> bool:
        numeric_count = 0
        for cell in row:
            cell_clean = (
                cell.strip().replace(",", ".").replace("-", "").replace("+", "")
            )
            try:
                float(cell_clean)
                numeric_count += 1
            except ValueError:
                continue
        return numeric_count > len(row) * 0.5

    header_idx = 0
    for i, row in enumerate(all_values):
        if i == 0 or not is_numeric_row(row):
            header_idx = i
            break

    headers = [h.strip().lower() for h in all_values[header_idx]]
    rows = all_values[header_idx + 1 :]

    existing_df = pd.DataFrame(rows, columns=headers)
    normalized = _normalize_df(existing_df)

    return set(normalized.apply(_compute_row_hash, axis=1))


def _normalize_value(v: object) -> str:
    if isinstance(v, str):
        v = v.strip().lower()
        # Пробуем распарсить строковые даты из Sheets (формат M/D/YYYY H:MM:SS)
        for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(v, fmt)  # noqa: DTZ007
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return v
    try:
        if pd.isna(v):
            return ""
    except TypeError, ValueError:
        pass
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip().lower()


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализовать DataFrame для корректного хэширования."""
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].map(_normalize_value)
    return df


def _compute_row_hash(row: pd.Series) -> str:
    return hashlib.sha256("".join(row.values).encode()).hexdigest()
