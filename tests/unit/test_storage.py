"""单元测试：storage"""
import json
from pathlib import Path

from video_worker import storage


def test_create_job_dir(tmp_path):
    """job 目录创建 + 子目录"""
    jd = storage.create_job_dir("test_001", tmp_path, clean_if_exists=True)
    assert jd.exists()
    assert (jd / "input").is_dir()
    assert (jd / "work" / "clips").is_dir()
    assert (jd / "work" / "frames").is_dir()
    assert (jd / "work" / "triplets").is_dir()
    assert (jd / "logs").is_dir()
    assert (jd / "output").is_dir()


def test_clean_if_exists(tmp_path):
    """清理已存在目录"""
    jd = storage.create_job_dir("test_001", tmp_path, clean_if_exists=True)
    (jd / "work" / "clips" / "old.mp4").write_bytes(b"old")

    jd2 = storage.create_job_dir("test_001", tmp_path, clean_if_exists=True)
    assert not (jd2 / "work" / "clips" / "old.mp4").exists()


def test_setup_logger(tmp_path):
    jd = storage.create_job_dir("test_001", tmp_path, clean_if_exists=True)
    logger = storage.setup_logger("test_001", jd)
    logger.info("hello")
    logger.info("world")
    log_path = storage.get_log_path(jd)
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "hello" in content
    assert "world" in content


def test_check_disk_space(tmp_path):
    ok, free = storage.check_disk_space(tmp_path, min_gb=0.0)
    assert ok is True
    assert free > 0
