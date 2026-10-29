"""Тести логіки конвертації відео.

Більшість тестів не запускають справжній ffmpeg: процес підмінюється
невеликим FakeProcess. Один короткий тест унизу справді генерує
1-секундне відео через testsrc і конвертує його.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import video_converter as vc

INFO = vc.MediaInfo(
    duration=10.0, width=1920, height=1080, has_video=True, has_audio=True
)
AUDIO_ONLY = vc.MediaInfo(
    duration=10.0, width=None, height=None, has_video=False, has_audio=True
)
VIDEO_ONLY = vc.MediaInfo(
    duration=10.0, width=640, height=480, has_video=True, has_audio=False
)


class FakeProcess:
    """Мінімальна заміна subprocess.Popen для тестів."""

    def __init__(
        self,
        args: list[str],
        stdout_lines: tuple[str, ...] = (),
        stderr_text: str = "",
        returncode: int = 0,
        output: bytes | None = b"result",
    ) -> None:
        self.args = args
        self.stdout = iter(stdout_lines)
        self.stderr = io.StringIO(stderr_text)
        self._stderr_text = stderr_text
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        if output is not None and args:
            Path(args[-1]).write_bytes(output)

    def communicate(self, timeout=None):
        return "", self._stderr_text

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


class VideoConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ffmpeg = mock.patch.object(
            vc, "_get_ffmpeg_exe", return_value="ffmpeg"
        )
        self.ffmpeg.start()
        self.addCleanup(self.ffmpeg.stop)

        self.temp = tempfile.TemporaryDirectory(prefix="file-toolkit-video-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def source(self, name: str = "clip.mp4") -> Path:
        path = self.folder / name
        path.write_bytes(b"source")
        return path

    # --- формати та імена ---------------------------------------------------

    def test_supported_suffixes(self) -> None:
        for suffix in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"):
            with self.subTest(suffix=suffix):
                self.assertTrue(vc.is_supported_video(Path("video" + suffix)))
                self.assertTrue(vc.is_supported_video(Path("VIDEO" + suffix.upper())))
        self.assertFalse(vc.is_supported_video(Path("video.txt")))
        with self.assertRaises(vc.UnsupportedVideoFormatError):
            vc.convert_video(
                self.source("clip.txt"),
                self.folder / "out.mp4",
                vc.VideoOptions(),
            )

    def test_labels_and_suffixes_cover_all_formats(self) -> None:
        self.assertEqual(set(vc.OUTPUT_SUFFIXES), set(vc.OutputFormat))
        self.assertEqual(set(vc.OUTPUT_FORMAT_LABELS), set(vc.OutputFormat))
        self.assertEqual(set(vc.QUALITY_LABELS), set(vc.QualityPreset))
        self.assertEqual(set(vc.HEIGHT_LABELS), set(vc.MaxHeight))

    def test_build_destination_avoids_source_and_existing_names(self) -> None:
        source = self.source()
        first = vc.build_destination(source, None, vc.VideoOptions(target=vc.OutputFormat.MP4))
        self.assertEqual(first.name, "clip_1.mp4")

        (self.folder / "clip.webm").write_bytes(b"old")
        (self.folder / "clip_1.webm").write_bytes(b"old")
        second = vc.build_destination(
            source, None, vc.VideoOptions(target=vc.OutputFormat.WEBM)
        )
        self.assertEqual(second.name, "clip_2.webm")

    def test_build_destination_uses_output_dir(self) -> None:
        source = self.source()
        output = self.folder / "out"
        output.mkdir()
        destination = vc.build_destination(
            source, output, vc.VideoOptions(target=vc.OutputFormat.MKV)
        )
        self.assertEqual(destination, output / "clip.mkv")

    def test_options_validate_crf(self) -> None:
        with self.assertRaises(ValueError):
            vc.VideoOptions(crf=64)
        with self.assertRaises(ValueError):
            vc.VideoOptions(crf=-1)
        self.assertEqual(vc.VideoOptions(crf=23).crf, 23)

    # --- probe --------------------------------------------------------------

    def test_probe_parses_duration_and_streams(self) -> None:
        source = self.source()
        stderr = (
            "Input #0, mov, from 'clip.mp4':\n"
            "  Duration: 00:00:10.50, start: 0.000000, bitrate: 1000 kb/s\n"
            "  Stream #0:0: Video: h264, yuv420p, 1920x1080, 30 fps\n"
            "  Stream #0:1: Audio: aac, 44100 Hz, stereo\n"
        )
        process = FakeProcess(["ffmpeg"], stderr_text=stderr, returncode=1, output=None)
        with mock.patch.object(vc, "_popen", return_value=process):
            info = vc.probe_media(source)
        self.assertAlmostEqual(info.duration or 0, 10.5)
        self.assertEqual((info.width, info.height), (1920, 1080))
        self.assertTrue(info.has_video)
        self.assertTrue(info.has_audio)

    def test_probe_detects_audio_only_and_ignores_cover_art(self) -> None:
        source = self.source()
        stderr = (
            "  Duration: 00:00:03.00, start: 0.000000, bitrate: 128 kb/s\n"
            "  Stream #0:0: Audio: mp3, 44100 Hz, stereo\n"
            "  Stream #0:1: Video: png, 600x600, 90k tbr (attached pic)\n"
        )
        process = FakeProcess(["ffmpeg"], stderr_text=stderr, returncode=1, output=None)
        with mock.patch.object(vc, "_popen", return_value=process):
            info = vc.probe_media(source)
        self.assertFalse(info.has_video)
        self.assertTrue(info.has_audio)

    def test_probe_corrupted_and_missing(self) -> None:
        source = self.source()
        process = FakeProcess(
            ["ffmpeg"],
            stderr_text="Invalid data found when processing input\n",
            returncode=1,
            output=None,
        )
        with mock.patch.object(vc, "_popen", return_value=process):
            with self.assertRaises(vc.CorruptedVideoError):
                vc.probe_media(source)

        with self.assertRaises(vc.SourceMissingError):
            vc.probe_media(self.folder / "absent.mp4")

    def test_probe_reports_missing_ffmpeg(self) -> None:
        source = self.source()
        with mock.patch.object(
            vc,
            "_get_ffmpeg_exe",
            side_effect=vc.FfmpegMissingError("немає ffmpeg"),
        ):
            with self.assertRaises(vc.FfmpegMissingError):
                vc.probe_media(source)

    # --- команди ffmpeg -----------------------------------------------------

    def command(
        self,
        target: vc.OutputFormat,
        *,
        info: vc.MediaInfo | None = INFO,
        max_height: vc.MaxHeight = vc.MaxHeight.P720,
        no_audio: bool = False,
        crf: int | None = None,
    ) -> list[str]:
        options = vc.VideoOptions(
            target=target,
            max_height=max_height,
            no_audio=no_audio,
            crf=crf,
        )
        return vc.build_command(
            self.folder / "in.mp4", self.folder / "out", options, info
        )

    def test_mp4_command_and_no_audio(self) -> None:
        command = self.command(vc.OutputFormat.MP4)
        self.assertIn("libx264", command)
        self.assertEqual(command[command.index("-crf") + 1], "23")
        self.assertIn("aac", command)
        self.assertIn("+faststart", command)
        self.assertIn("-f", command)

        silent = self.command(vc.OutputFormat.MP4, no_audio=True)
        self.assertIn("-an", silent)
        self.assertNotIn("-c:a", silent)

    def test_webm_mkv_and_custom_crf(self) -> None:
        webm = self.command(vc.OutputFormat.WEBM)
        self.assertIn("libvpx-vp9", webm)
        self.assertIn("libopus", webm)
        self.assertEqual(webm[webm.index("-crf") + 1], "33")

        mkv = self.command(vc.OutputFormat.MKV)
        self.assertIn("libx264", mkv)
        self.assertEqual(mkv[mkv.index("-f") + 1], "matroska")

        custom = self.command(vc.OutputFormat.MP4, crf=30)
        self.assertEqual(custom[custom.index("-crf") + 1], "30")
        clamped = self.command(vc.OutputFormat.MP4, crf=60)
        self.assertEqual(clamped[clamped.index("-crf") + 1], "51")

    def test_gif_command_uses_palette_and_no_audio(self) -> None:
        command = self.command(vc.OutputFormat.GIF)
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("palettegen", graph)
        self.assertIn("paletteuse", graph)
        self.assertIn("[out]", graph)
        self.assertEqual(command[command.index("-map") + 1], "[out]")
        self.assertIn("-an", command)
        self.assertEqual(command[command.index("-f") + 1], "gif")

    def test_audio_commands_extract_only_sound(self) -> None:
        mp3 = self.command(vc.OutputFormat.MP3)
        self.assertIn("-vn", mp3)
        self.assertIn("libmp3lame", mp3)
        self.assertEqual(mp3[mp3.index("-f") + 1], "mp3")

        wav = self.command(vc.OutputFormat.WAV)
        self.assertIn("-vn", wav)
        self.assertIn("pcm_s16le", wav)
        self.assertEqual(wav[wav.index("-f") + 1], "wav")

    def test_scale_filter_only_when_needed(self) -> None:
        scaled = self.command(vc.OutputFormat.MP4)
        self.assertEqual(
            scaled[scaled.index("-vf") + 1], "scale=-2:min(ih\\,720)"
        )

        small = self.command(
            vc.OutputFormat.MP4,
            info=vc.MediaInfo(10.0, 640, 480, True, True),
        )
        self.assertNotIn("-vf", small)

        unknown = self.command(vc.OutputFormat.MP4, info=None)
        self.assertIn("-vf", unknown)

    # --- конвертація --------------------------------------------------------

    def convert(self, source: Path, destination: Path, **options):
        opts = vc.VideoOptions(**options)
        return vc.convert_video(source, destination, opts)

    def test_success_is_atomic(self) -> None:
        source = self.source()
        destination = self.folder / "result.mp4"
        with (
            mock.patch.object(vc, "probe_media", return_value=INFO),
            mock.patch.object(
                vc,
                "_popen",
                side_effect=lambda args, **kwargs: FakeProcess(
                    args, output=b"converted"
                ),
            ),
        ):
            result = self.convert(source, destination)
        self.assertTrue(result.ok)
        self.assertEqual(destination.read_bytes(), b"converted")
        self.assertFalse(list(self.folder.glob(".file-toolkit-*")))

    def test_ffmpeg_errors_are_mapped(self) -> None:
        cases = (
            ("Invalid data found when processing input", vc.CorruptedVideoError),
            ("No space left on device", vc.NoSpaceError),
            ("Permission denied", vc.DestinationBusyError),
        )
        for stderr, expected in cases:
            with self.subTest(stderr=stderr):
                source = self.source()
                destination = self.folder / "result.mp4"
                with (
                    mock.patch.object(vc, "probe_media", return_value=INFO),
                    mock.patch.object(
                        vc,
                        "_popen",
                        side_effect=lambda args, **kwargs: FakeProcess(
                            args, stderr_text=stderr, returncode=1
                        ),
                    ),
                ):
                    with self.assertRaises(expected):
                        self.convert(source, destination)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.folder.glob(".file-toolkit-*")))

    def test_cancel_terminates_and_removes_temp(self) -> None:
        source = self.source()
        destination = self.folder / "result.mp4"
        state = {"started": False}

        def lines():
            state["started"] = True
            yield "progress=continue\n"

        processes: list[FakeProcess] = []

        def make_process(args, **kwargs):
            process = FakeProcess(args, stdout_lines=lines(), output=b"partial")
            processes.append(process)
            return process

        with (
            mock.patch.object(vc, "probe_media", return_value=INFO),
            mock.patch.object(vc, "_popen", side_effect=make_process),
        ):
            with self.assertRaises(vc.ConversionCancelled):
                vc.convert_video(
                    source,
                    destination,
                    vc.VideoOptions(),
                    should_cancel=lambda: state["started"],
                )
        self.assertTrue(processes[0].terminated)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.folder.glob(".file-toolkit-*")))

    def test_missing_streams_are_reported(self) -> None:
        source = self.source()
        destination = self.folder / "result.mp4"
        with mock.patch.object(vc, "probe_media", return_value=AUDIO_ONLY):
            with self.assertRaises(vc.NoVideoStreamError):
                self.convert(source, destination)

        with mock.patch.object(vc, "probe_media", return_value=VIDEO_ONLY):
            with self.assertRaises(vc.NoAudioStreamError):
                self.convert(
                    source, destination, target=vc.OutputFormat.MP3
                )

    def test_no_space_is_checked_before_running(self) -> None:
        source = self.source()
        destination = self.folder / "result.mp4"
        usage = mock.Mock(free=0)
        with (
            mock.patch.object(vc, "probe_media", return_value=INFO),
            mock.patch.object(vc.shutil, "disk_usage", return_value=usage),
        ):
            with self.assertRaises(vc.NoSpaceError):
                self.convert(source, destination)

    def test_batch_continues_after_error_and_reports_progress(self) -> None:
        sources = [self.source("bad.mp4"), self.source("good.mp4")]
        events: list[tuple] = []

        def fake_convert(source, destination, options, *, on_fraction=None, should_cancel=None):
            if on_fraction is not None:
                on_fraction(0.5)
            if source.name == "bad.mp4":
                raise vc.CorruptedVideoError("пошкоджено")
            return vc.VideoConversionResult(
                source=source, destination=destination, ok=True
            )

        with mock.patch.object(vc, "convert_video", side_effect=fake_convert):
            results = vc.convert_video_batch(
                sources,
                vc.VideoOptions(),
                self.folder,
                on_progress=lambda *event: events.append(event),
            )

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].ok)
        self.assertTrue(results[1].ok)
        self.assertEqual(events[-1][0], 2)
        self.assertEqual(events[-1][1], 2)
        self.assertIsNone(events[-1][2])

    def test_batch_stops_on_cancel(self) -> None:
        sources = [self.source("one.mp4"), self.source("two.mp4")]
        with mock.patch.object(
            vc, "convert_video", side_effect=vc.ConversionCancelled("stop")
        ):
            results = vc.convert_video_batch(sources, vc.VideoOptions())
        self.assertEqual(results, [])


def _ffmpeg_available() -> bool:
    try:
        process = subprocess.run(
            [vc._get_ffmpeg_exe(), "-version"],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        return False
    return process.returncode == 0


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg недоступний")
class RealFfmpegTests(unittest.TestCase):
    def test_testsrc_conversion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="file-toolkit-video-real-") as raw:
            folder = Path(raw)
            source = folder / "input.mp4"
            destination = folder / "output.mp4"
            generation = [
                vc._get_ffmpeg_exe(),
                "-hide_banner",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=15",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(source),
            ]
            subprocess.run(generation, capture_output=True, timeout=60, check=True)

            result = vc.convert_video(
                source,
                destination,
                vc.VideoOptions(
                    target=vc.OutputFormat.MP4,
                    quality=vc.QualityPreset.BALANCED,
                    max_height=vc.MaxHeight.P480,
                ),
            )

            self.assertTrue(result.ok)
            self.assertTrue(destination.is_file())
            self.assertGreater(destination.stat().st_size, 0)
            self.assertIsNotNone(result.duration)
            self.assertAlmostEqual(result.duration or 0, 1.0, delta=0.3)
            self.assertFalse(list(folder.glob(".file-toolkit-*")))


if __name__ == "__main__":
    unittest.main()
