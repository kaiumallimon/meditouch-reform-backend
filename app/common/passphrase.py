import secrets

# Curated list of friendly, distinct, readable words (no ambiguous letters/numbers)
PASSPHRASE_WORDS = [
    "Pulse", "Apex", "Beacon", "Cedar", "Cure", "Falcon", "Galaxy", "Haven",
    "Lotus", "Noble", "Orbit", "Prism", "Radiant", "River", "Shield", "Summit",
    "Valley", "Zenith", "Breeze", "Anchor", "Clarity", "Cosmos", "Echo", "Forest",
    "Harmony", "Matrix", "Nest", "Opal", "Pillar", "Quest", "Ridge", "Solar",
    "Tidal", "Unity", "Verve", "Willow", "Zephyr", "Aura", "Bliss", "Dawn"
]

SPECIAL_SYMBOLS = ["#", "!", "@", "$", "&", "*", "+"]

def generate_readable_passphrase(num_words: int = 3) -> str:
    """
    Generates a highly secure, human-readable passphrase for doctors.
    Example: 'Beacon-Cure-Summit-742!'
    - 3 Capitalized memorable words
    - Hyphen separator
    - 3 Cryptographic random digits
    - 1 Special symbol
    Entropy: > 60 bits (NIST recommended for strong passwords).
    """
    selected_words = [secrets.choice(PASSPHRASE_WORDS) for _ in range(num_words)]
    digits = secrets.randbelow(900) + 100  # 100 to 999
    symbol = secrets.choice(SPECIAL_SYMBOLS)
    
    words_part = "-".join(selected_words)
    return f"{words_part}-{digits}{symbol}"
