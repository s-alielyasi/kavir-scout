"""Persian text and exact product comparison."""
import re
import unicodedata

TRANSLATION = str.maketrans('يك۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', 'یک01234567890123456789')


def normalize_text(value: str) -> str:
    """Normalize Unicode, Persian letters, digits, joiners and whitespace."""
    value = unicodedata.normalize('NFKC', value).translate(TRANSLATION)
    value = re.sub(r'[\u200c\u200d\u200e\u200f\ufeff]', ' ', value)
    return ' '.join(value.split())


def text_pattern(text: str) -> re.Pattern[str]:
    """A semantic locator pattern tolerant of Arabic/Persian spelling variants."""
    parts = []
    for char in normalize_text(text):
        if char == ' ':
            parts.append(r'[\s\u200c\u200d]*')
        elif char == 'ی':
            parts.append('[یي]')
        elif char == 'ک':
            parts.append('[کك]')
        elif char in '0123456789':
            n = int(char)
            parts.append(f'[{char}{chr(0x6f0+n)}{chr(0x660+n)}]')
        else:
            parts.append(re.escape(char))
    boundary = r'[a-zA-Z0-9]' if normalize_text(text).isascii() else r'\w'
    return re.compile(r'(?<!' + boundary + ')' + ''.join(parts) + r'(?!' + boundary + ')', re.I)


def matches_product(text: str, product: str, size: str) -> bool:
    """Require the full model and full size in the same container."""
    normalized = normalize_text(text)
    return bool(text_pattern(product).search(normalized)
                and text_pattern(size).search(normalized))


def parse_quantity(value: str) -> int | None:
    value = normalize_text(value)
    match = re.fullmatch(r'([0-9]+)(?:\s*(?:حلقه|تایر|عدد))?', value)
    return int(match[1]) if match else None
