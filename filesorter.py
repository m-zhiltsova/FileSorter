#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileSorter 0.1 (MVP) — Умный сортировщик файлов.

Зависимости:
    pip install pyyaml
    sudo apt install trash-cli   (Linux)
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Проверка pyyaml ──────────────────────────────
try:
    import yaml
except ImportError:
    print("❌ ОШИБКА: Библиотека 'pyyaml' не установлена!")
    print()
    print("   Установите её командой:")
    print("       pip install pyyaml")
    print()
    print("   Или, если у вас несколько версий Python:")
    print("       pip3 install pyyaml")
    try:
        input("\n⏎ Нажмите Enter для выхода...")
    except EOFError:
        pass
    sys.exit(1)

# ── Логирование ──────────────────────────────────
LOG_DIR = Path.home() / ".filesorter"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "filesorter.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("FileSorter")


# ── Валидация конфигурации ───────────────────────
def load_and_validate_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.error("ERROR CONFIG_NOT_FOUND: Файл конфигурации не найден: %s", path)
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error("ERROR CONFIG_INVALID: Ошибка парсинга YAML — %s", e)
        sys.exit(1)

    if not isinstance(config, dict) or config.get("version") != 1:
        logger.error(
            "ERROR CONFIG_INVALID: Поле 'version' обязательно и должно быть равно 1"
        )
        sys.exit(1)

    scan_paths = config.get("scan_paths", [])
    if not scan_paths:
        logger.error("ERROR CONFIG_INVALID: 'scan_paths' не может быть пустым")
        sys.exit(1)

    for sp in scan_paths:
        p = Path(sp)
        if not p.exists() or not p.is_dir():
            logger.error("ERROR PATH_NOT_FOUND: Каталог не найден: %s", sp)
            sys.exit(1)

    for rule in config.get("sort_rules", []):
        ext = rule.get("extension", "")
        if not ext.startswith("."):
            logger.error(
                "ERROR INVALID_RULE: extension должен начинаться с точки: '%s'", ext
            )
            sys.exit(1)
        if not rule.get("destination"):
            logger.error("ERROR INVALID_RULE: destination не указан")
            sys.exit(1)

    archive_path = config.get("archive_path")
    for rule in config.get("cleanup_rules", []):
        days = rule.get("older_than_days", 0)
        if not isinstance(days, int) or days <= 0:
            logger.error(
                "ERROR INVALID_RULE: older_than_days должно быть > 0 (получено: %s)",
                days,
            )
            sys.exit(1)
        action = rule.get("action")
        if action not in ("trash", "archive"):
            logger.error(
                "ERROR INVALID_RULE: action должно быть 'trash' или 'archive' (получено: '%s')",
                action,
            )
            sys.exit(1)
        if action == "archive" and not archive_path:
            logger.error(
                "ERROR CONFIG_INVALID: archive_path не указан, но есть правило archive"
            )
            sys.exit(1)
        if action == "archive" and archive_path:
            for sp in scan_paths:
                if str(Path(archive_path).resolve()).startswith(
                    str(Path(sp).resolve())
                ):
                    logger.error(
                        "ERROR INVALID_RULE: archive_path внутри scan_paths"
                    )
                    sys.exit(1)

    return config


# ── Сканер ───────────────────────────────────────
def scan_files(scan_paths: list):
    files = []
    for base_path in scan_paths:
        base = Path(base_path).resolve()
        try:
            for path in base.rglob("*"):
                if path.is_file() and not path.name.startswith("."):
                    files.append((path, base))
        except PermissionError:
            logger.error("ERROR PERMISSION_DENIED: Нет доступа к %s", base)
    return files


# ── Планировщик ──────────────────────────────────
def plan_operations(files: list, config: dict) -> list:
    operations = []
    now = datetime.now()
    sort_rules = config.get("sort_rules", [])
    cleanup_rules = config.get("cleanup_rules", [])
    archive_base = Path(config.get("archive_path", ""))

    for file_path, base_scan_path in files:
        matched = False

        # Сортировка
        ext = file_path.suffix.lower()
        for rule in sort_rules:
            if rule["extension"].lower() == ext:
                dest_dir = base_scan_path / rule["destination"]
                if file_path.parent.resolve() == dest_dir.resolve():
                    matched = True
                    break
                dest_path = dest_dir / file_path.name
                operations.append(
                    {
                        "source": file_path,
                        "destination": dest_path,
                        "action": "move",
                        "type": "sort",
                    }
                )
                matched = True
                break

        if matched:
            continue

        # Очистка
        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        except OSError:
            continue
        age_days = (now - mtime).days

        for rule in cleanup_rules:
            if "path" in rule:
                rule_path = Path(rule["path"]).resolve()
                if not str(file_path.resolve()).startswith(str(rule_path)):
                    continue
            if age_days >= rule["older_than_days"]:
                action = rule["action"]
                if action == "trash":
                    operations.append(
                        {
                            "source": file_path,
                            "destination": None,
                            "action": "trash",
                            "type": "cleanup",
                        }
                    )
                elif action == "archive":
                    rel = file_path.relative_to(base_scan_path)
                    dest_path = archive_base / rel
                    operations.append(
                        {
                            "source": file_path,
                            "destination": dest_path,
                            "action": "move",
                            "type": "archive",
                        }
                    )
                matched = True
                break

    return operations


# ── Разрешение конфликтов имён ───────────────────
def get_safe_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


# ── Исполнитель ──────────────────────────────────
def execute_operations(operations: list, dry_run: bool) -> dict:
    stats = {"sorted": 0, "archived": 0, "trashed": 0, "errors": 0}

    for op in operations:
        src = op["source"]
        dest = op.get("destination")

        if dry_run:
            dest_str = str(dest) if dest else "TRASH"
            logger.info("PLAN: %s %s -> %s", op["action"].upper(), src, dest_str)
            if op["type"] == "sort":
                stats["sorted"] += 1
            elif op["type"] == "archive":
                stats["archived"] += 1
            elif op["type"] == "cleanup":
                stats["trashed"] += 1
            continue

        try:
            if op["action"] == "move":
                if not src.exists():
                    logger.warning("SKIP: файл исчез до перемещения: %s", src)
                    continue
                safe_dest = get_safe_path(dest)
                safe_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(safe_dest))
                if op["type"] == "sort":
                    stats["sorted"] += 1
                elif op["type"] == "archive":
                    stats["archived"] += 1

            elif op["action"] == "trash":
                if not src.exists():
                    logger.warning("SKIP: файл исчез: %s", src)
                    continue
                result = subprocess.run(
                    ["trash-put", str(src)], capture_output=True, text=True
                )
                if result.returncode != 0:
                    logger.error(
                        "ERROR TRASH_ERROR: %s — %s", src, result.stderr.strip()
                    )
                    stats["errors"] += 1
                    continue
                stats["trashed"] += 1

        except PermissionError:
            logger.error("ERROR PERMISSION_DENIED: %s", src)
            stats["errors"] += 1
        except FileNotFoundError:
            logger.error(
                "ERROR MOVE_ERROR: trash-cli не найден. Установите: sudo apt install trash-cli"
            )
            stats["errors"] += 1
        except Exception as e:
            logger.error("ERROR MOVE_ERROR: %s — %s", src, e)
            stats["errors"] += 1

    return stats


# ── CLI ──────────────────────────────────────────
def main():
    print()
    print("  FileSorter 0.1 (MVP)")
    print("  ====================")
    print()

    parser = argparse.ArgumentParser(
        prog="filesorter", description="Умный сортировщик файлов"
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Запуск обработки")
    run_p.add_argument("--config", required=True, help="Путь к YAML-конфигу")
    run_p.add_argument(
        "--dry-run", action="store_true", help="Только показать план"
    )

    val_p = sub.add_parser("validate", help="Проверка конфига")
    val_p.add_argument("--config", required=True, help="Путь к YAML-конфигу")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "validate":
        load_and_validate_config(args.config)
        print("\n✅ OK: Конфигурация валидна.")
        return

    if args.command == "run":
        config = load_and_validate_config(args.config)

        logger.info("Scanning %s ...", ", ".join(config["scan_paths"]))
        files = scan_files(config["scan_paths"])
        logger.info("Found: %d files", len(files))

        if not files:
            print("\nNo files matched the configured rules.")
            return

        operations = plan_operations(files, config)

        if args.dry_run:
            logger.info("--- DRY-RUN MODE ---")

        stats = execute_operations(operations, args.dry_run)

        scanned = len(files)
        processed = (
            stats["sorted"] + stats["archived"] + stats["trashed"] + stats["errors"]
        )
        skipped = scanned - processed

        summary = (
            f"scanned={scanned}, sorted={stats['sorted']}, "
            f"archived={stats['archived']}, trashed={stats['trashed']}, "
            f"skipped={skipped}, errors={stats['errors']}"
        )

        if args.dry_run:
            print(f"\nSummary: {summary}")
            print("DRY-RUN: no files were changed.")
        else:
            print(f"\nOK: {summary}")
            print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Прервано пользователем.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
