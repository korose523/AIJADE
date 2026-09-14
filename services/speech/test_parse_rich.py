"""Standalone unit test for SenseVoice rich-tag parsing.

Run without the full server / GPU:
    python test_parse_rich.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sensevoice_asr_server import _parse_rich  # noqa: E402


def check(label, text, exp_text, exp_lang, exp_emo, exp_events):
    got_text, got_lang, got_emo, got_events = _parse_rich(text)
    ok = (
        got_text == exp_text
        and got_lang == exp_lang
        and got_emo == exp_emo
        and got_events == exp_events
    )
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}")
    if not ok:
        print(f"    text : got={got_text!r} exp={exp_text!r}")
        print(f"    lang : got={got_lang!r} exp={exp_lang!r}")
        print(f"    emo  : got={got_emo!r} exp={exp_emo!r}")
        print(f"    event: got={got_events!r} exp={exp_events!r}")
    return ok


def main():
    results = []
    results.append(
        check(
            "chinese neutral speech",
            "<|zh|><|NEUTRAL|><|Speech|>今天天气真好",
            "今天天气真好",
            "zh",
            "neutral",
            ["Speech"],
        )
    )
    results.append(
        check(
            "english happy",
            "<|en|><|HAPPY|><|Speech|>I am so happy to see you",
            "I am so happy to see you",
            "en",
            "happy",
            ["Speech"],
        )
    )
    results.append(
        check(
            "emotion only, no speech event tag",
            "<|zh|><|ANGRY|>你为什么这样",
            "你为什么这样",
            "zh",
            "angry",
            [],
        )
    )
    results.append(
        check(
            "audio event laughter",
            "<|ja|><|SURPRISED|><|Laughter|>おどろいた",
            "おどろいた",
            "ja",
            "surprised",
            ["Laughter"],
        )
    )
    results.append(
        check(
            "plain text no tags",
            "just some text",
            "just some text",
            "unknown",
            "neutral",
            [],
        )
    )
    results.append(
        check(
            "korean sad with applause",
            "<|ko|><|SAD|><|Applause|>슬퍼요",
            "슬퍼요",
            "ko",
            "sad",
            ["Applause"],
        )
    )
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
