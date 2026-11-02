"""Synthetic browser fixtures shared by browser and safety regressions."""
import os

from config import Config

PRODUCT = 'Perfect (R14) KB27'
SIZE = '185/65R14'


def fixture_config():
    # Four is intentional test data for quantity/cap regressions, not the app default.
    return Config.from_env({'TARGET_QUANTITY': '4',
                            'BROWSER_CHANNEL': os.environ.get('TEST_BROWSER_CHANNEL', '')})


def row(size=SIZE, quantity='4', maximum='4'):
    return (f'<article>{PRODUCT} <span>{size}</span>'
            f'<label>تعداد<input type="number" value="{quantity}" max="{maximum}"></label>'
            '<button>انتخاب</button></article>')


async def offline_context(browser):
    context = await browser.new_context()
    # Later fixture routes take precedence; unmatched requests never reach a live site.
    await context.route('**/*', lambda route: route.abort())
    return context
