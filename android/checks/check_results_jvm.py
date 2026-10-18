"""Лёгкая JVM-проверка TASK-19 из существующего кэша: без Gradle, сети загрузок и APK."""

import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[1]
CACHE = ANDROID / ".gradle/user-home/caches/modules-2/files-2.1"
JAVA = Path(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk")) / "bin/java"


def jar(name, version):
    paths = list(CACHE.glob(f"*/{name}/{version}/*/*.jar"))
    if len(paths) != 1:
        raise SystemExit(f"Нужен уже имеющийся кэш {name}:{version}; загрузка не выполняется")
    return str(paths[0])


def run(command, timeout):
    result = subprocess.run(command, timeout=timeout)
    if result.returncode:
        raise SystemExit(result.returncode)


runtime = [
    jar(name, version)
    for name, version in (
        ("kotlin-stdlib", "2.0.21"),
        ("annotations", "23.0.0"),
        ("kotlinx-coroutines-core-jvm", "1.7.3"),
        ("kotlinx-serialization-core-jvm", "1.7.3"),
        ("kotlinx-serialization-json-jvm", "1.7.3"),
        ("retrofit", "2.11.0"),
        ("okhttp", "4.12.0"),
        ("okio-jvm", "3.6.0"),
        ("retrofit2-kotlinx-serialization-converter", "1.0.0"),
        ("junit", "4.13.2"),
        ("hamcrest-core", "1.3"),
        ("mockwebserver", "4.12.0"),
    )
]
compiler = [
    jar(name, version)
    for name, version in (
        ("kotlin-compiler-embeddable", "2.0.21"),
        ("kotlin-stdlib", "2.0.21"),
        ("kotlin-script-runtime", "2.0.21"),
        ("kotlin-reflect", "1.6.10"),
        ("kotlin-daemon-embeddable", "2.0.21"),
        ("trove4j", "1.0.20200330"),
        ("kotlinx-coroutines-core-jvm", "1.6.4"),
        ("annotations", "23.0.0"),
    )
]
main = ANDROID / "app/src/main/java/com/shadeai/app"
tests = ANDROID / "app/src/test/java/com/shadeai/app"
sources = [
    main / "core/config/ServerAddress.kt",
    main / "core/network/Models.kt",
    main / "core/network/ShadeApi.kt",
    main / "core/network/CoreResults.kt",
    main / "ui/CoreResultsController.kt",
    main / "ui/CoreResultsPresentation.kt",
    *list(tests.glob("CoreResults*Test.kt")),
]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--compile-app", action="store_true", help="Также скомпилировать Kotlin/Compose без APK/Gradle"
)
args = parser.parse_args()
if shutil.disk_usage(ANDROID).free < 512 * 1024**2:
    raise SystemExit("Для лёгкой проверки требуется минимум 512 MiB свободного места")
with tempfile.TemporaryDirectory(prefix="task19-jvm-", dir=ANDROID / ".gradle") as temp:
    classes = Path(temp) / "classes"
    run(
        [
            str(JAVA),
            "-Xmx512m",
            "-cp",
            os.pathsep.join(compiler),
            "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
            "-no-stdlib",
            "-no-reflect",
            "-jvm-target",
            "17",
            "-classpath",
            os.pathsep.join(runtime),
            "-Xplugin=" + jar("kotlin-serialization-compiler-plugin-embeddable", "2.0.21"),
            "-d",
            str(classes),
            *map(str, sources),
        ],
        timeout=120,
    )
    run(
        [
            str(JAVA),
            "-Xmx128m",
            "-cp",
            os.pathsep.join([str(classes), *runtime]),
            "org.junit.runner.JUnitCore",
            "com.shadeai.app.CoreResultsPresentationTest",
            "com.shadeai.app.CoreResultsControllerTest",
            "com.shadeai.app.CoreResultsNetworkTest",
        ],
        timeout=60,
    )
    if args.compile_app:
        extracted = []
        total = 0
        for index, archive in enumerate(sorted(CACHE.rglob("*.aar"))):
            with zipfile.ZipFile(archive) as aar:
                if "classes.jar" not in aar.namelist():
                    continue
                content = aar.read("classes.jar")
                total += len(content)
                if (
                    total > 100 * 1024**2
                    or shutil.disk_usage(ANDROID).free < len(content) + 512 * 1024**2
                ):
                    raise SystemExit("Бюджет временных AAR-классов исчерпан; APK не собирается")
                path = Path(temp) / f"aar-{index}.jar"
                path.write_bytes(content)
                extracted.append(str(path))
        androidx = [str(p) for p in CACHE.glob("androidx.*/*/*/*/*.jar")]
        auxiliary = [str(p) for p in CACHE.glob("com.google.guava/*/*/*/*.jar")]
        android_jar = ANDROID / ".gradle/sdk/platforms/android-35/android.jar"
        app_classpath = [*runtime, str(android_jar), *extracted, *androidx, *auxiliary]
        print(f"Временные AAR-классы: {total} байт; Gradle-кэш не создаётся", flush=True)
        run(
            [
                str(JAVA),
                "-Xmx512m",
                "-cp",
                os.pathsep.join(compiler),
                "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                "-no-stdlib",
                "-no-reflect",
                "-jvm-target",
                "17",
                "-classpath",
                os.pathsep.join(app_classpath),
                "-Xplugin=" + jar("kotlin-serialization-compiler-plugin-embeddable", "2.0.21"),
                "-Xplugin=" + jar("kotlin-compose-compiler-plugin-embeddable", "2.0.21"),
                "-d",
                str(Path(temp) / "app-classes"),
                *map(str, main.rglob("*.kt")),
            ],
            timeout=120,
        )
        print(
            "Kotlin/Compose исходники приложения скомпилированы. "
            "APK/манифест/lint/эмулятор НЕ проверены."
        )
print("JVM-тесты завершены, временные классы удалены. Это не полная Android-сборка.")
