NOTE_FIELDS = ("operator", "wearing", "channels", "actions")


def clean_notes(notes):
    if notes is None:
        return {}
    if not isinstance(notes, dict):
        raise ValueError("采集记录格式不正确。")
    if not notes:
        return {}
    return {key: str(notes.get(key, "")).strip()[:2000] for key in NOTE_FIELDS}
