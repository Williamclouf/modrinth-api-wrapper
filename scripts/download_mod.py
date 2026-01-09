"""Minecraft batch mod downloader for Modrinth"""
import sys
import json
import datetime
import logging
import argparse
from typing import Optional, List
from enum import Enum
from pathlib import Path


from modrinth_api_wrapper.models import *
from modrinth_api_wrapper.client import Client
from modrinth_api_wrapper.network import CLIENT
from modrinth_api_wrapper.expections import ResponseCodeException


logger = logging.getLogger(__name__)
logger.propagate = False
handler = logging.StreamHandler()
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


class ModLoader(str, Enum):
    FABRIC = "fabric"
    FORGE = "forge"
    QUILT = "quilt"
    NEOFORGE = "neoforge"


class FileDownloader(File):
    def download(self, download_path: Path) -> None:
        url = self.url
        filename = self.filename
        filepath = download_path / filename

        response = CLIENT.get(url)
        response.raise_for_status()

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(response.content)


def parse_file(file_path: Path) -> List[str]:
    """从文本文件中解析mod列表, 忽略空行和注释行"""
    try:
        lines = file_path.read_text().splitlines()
    except Exception as e:
        logger.error(f"文件读取失败")
        sys.exit(1)

    mods = list(filter(lambda x: x and not x.startswith("#"), map(str.strip, lines)))

    return mods


def get_latest_release_version(versions: List[Version]) -> Optional[Version]:
    """从版本列表中获取最新版本, Release优先"""

    def _filter(v: Version) -> bool:
        logger.debug(f"{v.game_versions}, {v.loaders}, {v.version_type}, {v.name}")
        return v.version_type == VersionType.RELEASE
    
    if len(versions) == 0:
        return None

    release_versions = list(filter(_filter, versions))

    if len(release_versions) == 0:
        release_versions = versions

    now = datetime.now()
    latest_version = min(
        release_versions,
        key=lambda v: abs((now.timestamp() - v.date_published.timestamp())),
    )

    return latest_version


def download_mod(v: Version, slug_id: str, download_path: Path) -> None:
    if not v.files:
        logger.error(f"{slug_id}({v.version_number}) 没有可下载的文件")
        return

    for file in v.files:
        fd = FileDownloader.model_validate(vars(file))
        fd.download(download_path)
        logger.info(f"{file.filename}")


def cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="Input text file containing mod slugs or ids, one per line",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        help="Directory to save downloaded mods",
    )
    parser.add_argument(
        "--category",
        type=str,
        required=True,
        choices=[loader.value for loader in ModLoader],
        help="Mod loader type",
    )
    parser.add_argument(
        "--version", type=str, required=True, help="Minecraft version number"
    )
    parser.add_argument(
        "mods", nargs="*", help="List of mod slugs or ids to download, space separated"
    )

    args = parser.parse_args()

    if not args.file and not args.mods:
        parser.error("Must specify either --file parameter or provide mod list directly")

    if args.file:
        f = Path(args.file).resolve()
        args.mods += parse_file(f)

    args.output_dir = Path(args.output_dir or ".").resolve()

    return args


def main():
    args = cli()
    client = Client()

    for project_id in args.mods:
        loader_s = json.dumps([args.category])
        version_s = json.dumps([args.version])

        try:
            versions = client.list_project_versions(
                project_id=project_id,
                params={"loaders": loader_s, "game_versions": version_s},
            )
        except ResponseCodeException as e:
            if e.status_code == 404:
                logger.error(f"mod slug_id 错误: {project_id}")
            else:
                logger.error(f"发生错误: {e.__class__.__name__}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"发生错误: {e.__class__.__name__}")
            sys.exit(1)

        logger.debug(f"{project_id} {args.category} versions, get {len(versions)}")

        target = get_latest_release_version(versions)
        if target is None:
            logger.warning(f"未能找到 {project_id} 的 {args.category} 版本，请手动下载")
            continue

        download_mod(target, project_id, args.output_dir)


if __name__ == "__main__":
    main()
