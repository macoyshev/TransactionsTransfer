from pathlib import Path

import typer
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.async_api import async_playwright

PROFILE_DIR = Path(__file__).parent.parent / ".tbank_profile"

LOGIN_URL = "https://www.tbank.ru/login/"

OPERATIONS_URL = "https://www.tbank.ru/mybank/operations/"

DROPDOWN_BTN = '[data-qa-type="molecule-export-dropdown-operations-button.icon"]'
XLSX_ITEM = (
    '[data-qa-type="click-area molecule-export-dropdown-operations-menuItem '
    'molecule-export-dropdown-operations-menuItem-xlsx"]'
)
XLSX_ITEM_ALT = 'div:has-text("Скачать в Excel")'


async def save_session() -> None:
    """Сохранить сессию браузера для авторизации."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    typer.echo(f"[*] Профиль браузера: {PROFILE_DIR}")
    typer.echo("[*] Открываем страницу входа TBank …")
    typer.echo("[*] Авторизуйтесь вручную, затем нажмите Enter в терминале.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=100,
            args=["--start-maximized"],
            accept_downloads=True,
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

        typer.echo("")
        input("    >>> Войдите в личный кабинет и нажмите Enter: ")
        typer.echo("[✓] Сессия сохранена. Теперь можно запускать скрипт без login.")

        await context.close()


async def export_xlsx(
    range_start: int,
    range_end: int,
) -> tuple[bytes, str]:
    """Экспортировать операции в Excel."""
    url = _build_url(range_start, range_end)
    typer.echo(f"[*] URL:      {url}")
    typer.echo(f"[*] Диапазон: {range_start} → {range_end}")
    typer.echo(f"[*] Профиль:  {PROFILE_DIR}")

    if not PROFILE_DIR.exists():
        typer.echo("")
        typer.secho(
            "[!] Папка профиля не найдена. Сначала выполните авторизацию:",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            slow_mo=150,
            args=["--start-maximized"],
            accept_downloads=True,
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        typer.echo("[*] Открываем страницу операций …")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        if "/login" in page.url or "/auth" in page.url:
            typer.echo("")
            typer.secho(
                "[!] Сессия истекла — требуется повторная авторизация.",
                fg=typer.colors.RED,
            )
            typer.echo("    Запустите: python main.py login")
            await context.close()
            raise typer.Exit(1)

        typer.echo("[*] Ожидаем кнопку экспорта …")
        try:
            await page.wait_for_selector(DROPDOWN_BTN, timeout=30_000)
        except PlaywrightTimeoutError as err:
            typer.secho(
                "[!] Кнопка экспорта не появилась за 30 секунд.", fg=typer.colors.RED
            )
            await context.close()
            raise typer.Exit(1) from err

        typer.echo("[*] Открываем меню экспорта …")
        await page.click(DROPDOWN_BTN)

        xlsx_selector = XLSX_ITEM
        try:
            await page.wait_for_selector(XLSX_ITEM, timeout=8_000)
        except PlaywrightTimeoutError:
            try:
                await page.wait_for_selector(XLSX_ITEM_ALT, timeout=5_000)
                xlsx_selector = XLSX_ITEM_ALT
                typer.echo("[*] Используем запасной селектор (по тексту).")
            except PlaywrightTimeoutError as err:
                typer.secho(
                    "[!] Пункт «Скачать в Excel» не появился в меню.",
                    fg=typer.colors.RED,
                )
                await context.close()
                raise typer.Exit(1) from err

        typer.echo("[*] Нажимаем «Скачать в Excel» …")
        async with page.expect_download(timeout=60_000) as dl_info:
            await page.click(xlsx_selector)

        download = await dl_info.value
        filename = download.suggested_filename or "tbank_operations.xlsx"
        path = await download.path()
        data = path.read_bytes()
        await context.close()

    return data, filename


def _build_url(range_start: int, range_end: int) -> str:
    """Построить URL для страницы операций."""
    return f"{OPERATIONS_URL}?rangeStart={range_start}&rangeEnd={range_end}"
