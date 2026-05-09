import asyncio
import warnings
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from app import google_sheets, tbank, transactions

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
app = typer.Typer(
    help="Скачать выписку операций TBank в Excel и загрузить в Google Sheets.",
    add_completion=False,
)

DECEMBER = 12


@app.command()
def login() -> None:
    """Открыть браузер для ручной авторизации и сохранить сессию."""
    asyncio.run(tbank.save_session())


@app.command()
def main(
    year: Annotated[int, typer.Option(help="Год (например: 2026)")],
    month: Annotated[
        int | None, typer.Option(help="Месяц (1-12), если не указан — весь год")
    ] = None,
) -> None:
    """Скачать выписку операций TBank и загрузить в Google Sheets."""
    if month is not None:
        months = [month]
        typer.echo(f"[*] Диапазон: {year}-{month:02d} (месяц).")
    else:
        months = list(range(1, 13))
        typer.echo(f"[*] Диапазон: {year} (весь год).")

    for m in months:
        typer.echo(f"\n[*] Обрабатываем {year}-{m:02d} …")
        start_dt = datetime(year, m, 1, tzinfo=UTC)
        if m == DECEMBER:
            end_dt = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
        else:
            end_dt = datetime(year, m + 1, 1, tzinfo=UTC) - timedelta(microseconds=1)

        range_start = int(start_dt.timestamp() * 1000)
        range_end = int(end_dt.timestamp() * 1000)

        if transactions.range_exists(range_start, range_end):
            typer.echo("[*] Диапазон уже есть — пропускаем скачивание.")
        else:
            data, filename = asyncio.run(tbank.export_xlsx(range_start, range_end))
            transactions.save(data, filename)

    df = transactions.load(year=year, month=month)
    new_transactions = google_sheets.filter_new(df)
    google_sheets.upload(df=new_transactions)


if __name__ == "__main__":
    app()
