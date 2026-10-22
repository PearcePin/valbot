"""Download verified local Android build tools without changing system Java/Python."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".android-tools"


def read(url):
    return urllib.request.urlopen(url, timeout=60).read()


def download(name, url, algorithm=None, checksum=None):
    path = TOOLS / name
    if path.exists() and zipfile.is_zipfile(path):
        if not checksum or hashlib.new(algorithm, path.read_bytes()).hexdigest() == checksum:
            return path
    print("Downloading/resuming " + name, flush=True)
    total = None
    attempts = 0
    while total is None or path.stat().st_size < total:
        start = path.stat().st_size if path.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{start + 4 * 1024 * 1024 - 1}"})
        try:
            with urllib.request.urlopen(request, timeout=90) as source:
                content_range = source.headers.get("Content-Range", "")
                if start and not content_range.startswith(f"bytes {start}-"):
                    raise RuntimeError("Server did not honor resume range")
                total = int(content_range.partition("/")[2]) if content_range else int(source.headers["Content-Length"])
                with path.open("ab") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
            attempts = 0
            if path.stat().st_size == start:
                raise RuntimeError("Empty download chunk")
        except Exception:
            attempts += 1
            if attempts >= 8:
                raise
    if checksum and hashlib.new(algorithm, path.read_bytes()).hexdigest() != checksum:
        raise RuntimeError("Checksum mismatch: " + name)
    return path


def main():
    TOOLS.mkdir(exist_ok=True)
    packages = json.loads(read("https://api.azul.com/metadata/v1/zulu/packages/?java_version=17&os=windows&arch=x86&hw_bitness=64&archive_type=zip&java_package_type=jdk&latest=true&release_status=ga&availability_types=CA"))
    jdk = next(p for p in packages if "win_x64" in p["name"] and "crac" not in p["name"] and "-fx-" not in p["name"])
    repository = ET.fromstring(read("https://dl.google.com/android/repository/repository2-1.xml"))
    sdk_jobs = []
    for target, destination in (("platforms;android-35", "platforms/android-35"), ("build-tools;35.0.0", "build-tools/35.0.0")):
        package = next(p for p in repository.findall("remotePackage") if p.get("path") == target and
                       (target != "platforms;android-35" or any(a.findtext("complete/url") == "platform-35_r02.zip" for a in p.findall("archives/archive"))))
        archive = next(a for a in package.findall("archives/archive") if a.findtext("host-os") in (None, "windows"))
        url = archive.findtext("complete/url")
        checksum = archive.find("complete/checksum")
        sdk_jobs.append((url, "https://dl.google.com/android/repository/" + url, "sha1", checksum.text, destination))
    gradle_url = "https://downloads.gradle.org/distributions/gradle-8.13-bin.zip"
    gradle_sha = read(gradle_url + ".sha256").decode().strip()
    jobs = [("jdk.zip", jdk["download_url"], None, None), ("gradle.zip", gradle_url, "sha256", gradle_sha)]
    jobs += [job[:4] for job in sdk_jobs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        archives = list(pool.map(lambda job: download(*job), jobs))
    if not list(TOOLS.glob("zulu*/bin/java.exe")):
        with zipfile.ZipFile(archives[0]) as archive:
            archive.extractall(TOOLS)
    if not (TOOLS / "gradle-8.13/bin/gradle.bat").exists():
        with zipfile.ZipFile(archives[1]) as archive:
            archive.extractall(TOOLS)
    for path, job in zip(archives[2:], sdk_jobs):
        destination = TOOLS / "sdk" / job[4]
        if destination.exists():
            continue
        temporary = TOOLS / (path.stem + "-unpack")
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temporary)
        folder = next(p for p in temporary.iterdir() if p.is_dir())
        destination.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(destination)
    java_home = next(TOOLS.glob("zulu*/bin/java.exe")).parent.parent
    (ROOT / "android/local.properties").write_text("sdk.dir=" + (TOOLS / "sdk").as_posix() + "\n", encoding="utf-8")
    print(json.dumps({"java": str(java_home), "sdk": str(TOOLS / "sdk")}), flush=True)


if __name__ == "__main__":
    main()
