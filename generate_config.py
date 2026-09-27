#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileSorter — Мастер настройки конфигурации.
НЕ требует установки pyyaml. Просто запустите:
    python3 generate_config.py
"""

import os
import sys
from pathlib import Path


def pause():
    """Пауза перед закрытием, чтобы окно не исчезло."""
    try:
        input("\n⏎ Нажмите Enter для выхода...")
    except EOFError:
        pass


def ask(prompt, default=None):
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    while True:
        val = input(prompt).strip()
        if not val and default is not None:
            return default
        if val:
            return val
        print("  ⚠ Пустое значение недопустимо.")


def ask_yes_no(prompt):
    while True:
        val = input(f"{prompt} (y/n): ").strip().lower()
        if val in ('y', 'yes', 'д', 'да'):
            return True
        if val in ('n', 'no', 'н', 'нет'):
            return False
        print("  ⚠ Введите y или n.")


def ask_int(prompt, minimum=1):
    while True:
        val = input(prompt).strip()
        try:
            n = int(val)
            if n >= minimum:
                return n
            print(f"  ⚠ Число должно быть >= {minimum}.")
        except ValueError:
            print("  ⚠ Введите целое число.")


def yaml_escape(s):
    """Экранирует строку для YAML, если нужно."""
    if any(c in s for c in ':{}[],&*?|->!%@`#'):
        return f'"{s}"'
    return s


def build_yaml(config):
    """Собирает YAML-строку вручную, без pyyaml."""
    lines = []
    lines.append(f"version: {config['version']}")
    lines.append("")

    # scan_paths
    lines.append("scan_paths:")
    for p in config["scan_paths"]:
        lines.append(f"  - {yaml_escape(p)}")
    lines.append("")

    # sort_rules
    if config["sort_rules"]:
        lines.append("sort_rules:")
        for r in config["sort_rules"]:
            lines.append(f"  - extension: {yaml_escape(r['extension'])}")
            lines.append(f"    destination: {yaml_escape(r['destination'])}")
        lines.append("")

    # cleanup_rules
    if config["cleanup_rules"]:
        lines.append("cleanup_rules:")
        for r in config["cleanup_rules"]:
            lines.append("  -")
            if "path" in r:
                lines.append(f"    path: {yaml_escape(r['path'])}")
            lines.append(f"    older_than_days: {r['older_than_days']}")
            lines.append(f"    action: {yaml_escape(r['action'])}")
        lines.append("")

    # archive_path
    if config.get("archive_path"):
        lines.append(f"archive_path: {yaml_escape(config['archive_path'])}")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 55)
    print("  🚀  FileSorter — Мастер настройки конфигурации")
    print("=" * 55)
    print()
    print("Этот скрипт создаст файл config.yaml для FileSorter.")
    print("Отвечайте на вопросы, и конфигурация сгенерируется")
    print("автоматически. Никаких дополнительных библиотек не нужно.")
    print()

    config = {
        "version": 1,
        "scan_paths": [],
        "sort_rules": [],
        "cleanup_rules": [],
        "archive_path": "",
    }

    # --- Выходной файл ---
    out_file = ask("Куда сохранить конфигурацию", "config.yaml")

    # --- Шаг 1: scan_paths ---
    print()
    print("─" * 55)
    print("📂  Шаг 1: Директории для сканирования")
    print("─" * 55)
    print("Укажите папки, в которых FileSorter будет наводить порядок.")
    print("Введите 'done', когда закончите.")
    print()

    while True:
        raw = ask("Путь к директории (или 'done')")
        if raw.lower() == "done":
            break
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            print(f"  ℹ Папка {p} пока не существует — будет использована как есть.")
        elif not p.is_dir():
            print(f"  ⚠ {p} — это файл, а не папка. Пропускаем.")
            continue
        config["scan_paths"].append(str(p))
        print(f"  ✅ Добавлено: {p}")

    if not config["scan_paths"]:
        print("\n❌ Ошибка: нужно указать хотя бы одну директорию!")
        pause()
        sys.exit(1)

    # --- Шаг 2: sort_rules ---
    print()
    print("─" * 55)
    print("🗂️  Шаг 2: Правила сортировки по расширениям")
    print("─" * 55)
    print("Пример: .jpg → Images, .py → Code, .log → Logs")
    print()

    while ask_yes_no("Добавить правило сортировки?"):
        ext = ask("Расширение (например .jpg, .py, .log)").lower()
        if not ext.startswith("."):
            ext = "." + ext
            print(f"  ℹ Автоматически добавлена точка: {ext}")
        dest = ask("Целевая папка (например Images, Code, Logs)")
        config["sort_rules"].append({"extension": ext, "destination": dest})
        print(f"  ✅ {ext} → {dest}")

    # --- Шаг 3: cleanup_rules ---
    print()
    print("─" * 55)
    print("🧹  Шаг 3: Правила очистки старых файлов")
    print("─" * 55)
    print("Укажите, какие файлы считать старыми и что с ними делать.")
    print("  trash   — переместить в корзину (можно восстановить)")
    print("  archive — переместить в архивную папку")
    print()

    needs_archive = False
    while ask_yes_no("Добавить правило очистки?"):
        rule = {}
        path_filter = ask(
            "Применить только к конкретной папке? (Enter = ко всем)", ""
        )
        if path_filter:
            rule["path"] = str(Path(path_filter).expanduser().resolve())

        rule["older_than_days"] = ask_int("Файлы старше скольких дней? ", 1)

        while True:
            action = ask("Действие (trash / archive)", "trash").lower()
            if action in ("trash", "archive"):
                rule["action"] = action
                if action == "archive":
                    needs_archive = True
                break
            print("  ⚠ Допустимы только 'trash' или 'archive'.")

        config["cleanup_rules"].append(rule)
        scope = rule.get("path", "все папки")
        print(f"  ✅ >{rule['older_than_days']} дн. → {action} ({scope})")

    # --- Шаг 4: archive_path ---
    if needs_archive:
        print()
        print("─" * 55)
        print("📦  Шаг 4: Путь к архиву")
        print("─" * 55)
        default_archive = str(Path.home() / "filesorter-archive")
        archive = ask("Куда сохранять архивируемые файлы?", default_archive)
        config["archive_path"] = str(Path(archive).expanduser().resolve())

    # --- Генерация и сохранение ---
    print()
    print("─" * 55)
    print("💾  Генерация файла...")
    print("─" * 55)

    yaml_text = build_yaml(config)

    try:
        out_path = Path(out_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml_text, encoding="utf-8")
    except Exception as e:
        print(f"\n❌ Не удалось сохранить файл: {e}")
        pause()
        sys.exit(1)

    print()
    print("✅  Конфигурация успешно сохранена!")
    print(f"    Файл: {out_path}")
    print()
    print("─" * 55)
    print("📄  Содержимое config.yaml:")
    print("─" * 55)
    print(yaml_text)
    print("─" * 55)
    print()
    print("👉  Следующие шаги:")
    print(f"    1. Установите pyyaml:   pip install pyyaml")
    print(f"    2. Установите trash-cli: sudo apt install trash-cli")
    print(f"    3. Проверьте план:")
    print(f"       python3 filesorter.py run --config {out_path} --dry-run")
    print(f"    4. Запустите обработку:")
    print(f"       python3 filesorter.py run --config {out_path}")
    print()

    pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Настройка прервана.")
        pause()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        pause()
        sys.exit(1)
