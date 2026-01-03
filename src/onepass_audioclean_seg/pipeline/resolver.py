"""输入解析器：从各种输入形态解析出任务列表"""

import json
import logging
from pathlib import Path
from typing import Optional

from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.utils.paths import get_rel_key, sanitize_path_component, stable_hash

logger = logging.getLogger(__name__)


class InputResolver:
    """输入解析器：支持 file/workdir/root/manifest 四种输入类型"""
    
    def __init__(self, pattern: str = "audio.wav"):
        """
        Args:
            pattern: 扫描根目录时使用的文件名模式（默认: audio.wav）
        """
        self.pattern = pattern
    
    def resolve(self, input_path: Path, out_root: Path, out_mode: str) -> list[SegJob]:
        """解析输入路径，返回任务列表
        
        Args:
            input_path: 输入路径（文件或目录）
            out_root: 输出根目录
            out_mode: 输出模式（in_place 或 out_root）
        
        Returns:
            任务列表
        """
        input_path = input_path.resolve()
        
        if not input_path.exists():
            raise FileNotFoundError(f"输入路径不存在: {input_path}")
        
        if input_path.is_file():
            # 判断是单个音频文件还是 manifest.jsonl
            if input_path.name == "manifest.jsonl":
                return self._resolve_manifest(input_path, out_root, out_mode)
            else:
                return self._resolve_single_file(input_path, out_root, out_mode)
        elif input_path.is_dir():
            # 判断是单个 workdir 还是批处理根目录
            audio_file = input_path / "audio.wav"
            if audio_file.exists():
                return self._resolve_workdir(input_path, out_root, out_mode)
            else:
                return self._resolve_root(input_path, out_root, out_mode)
        else:
            raise ValueError(f"输入路径既不是文件也不是目录: {input_path}")
    
    def _resolve_single_file(self, audio_path: Path, out_root: Path, out_mode: str) -> list[SegJob]:
        """解析单个音频文件"""
        audio_path = audio_path.resolve()
        workdir = None
        meta_path = None
        
        # 生成 job_id 和 rel_key
        stem = audio_path.stem
        rel_key = stem
        job_id = f"job_{stable_hash(str(audio_path.resolve()))}"
        
        # 确定输出目录
        if out_mode == "in_place":
            # 单文件输入，输出到 out_root/<stem>/seg
            out_dir = out_root / sanitize_path_component(stem) / "seg"
        else:  # out_root
            out_dir = out_root / sanitize_path_component(stem) / "seg"
        
        job = SegJob(
            job_id=job_id,
            input_type="file",
            workdir=workdir,
            audio_path=audio_path,
            meta_path=meta_path,
            out_dir=out_dir,
            rel_key=rel_key,
        )
        return [job]
    
    def _resolve_workdir(self, workdir: Path, out_root: Path, out_mode: str) -> list[SegJob]:
        """解析单个 workdir（包含 audio.wav 的目录）"""
        workdir = workdir.resolve()
        audio_path = workdir / "audio.wav"
        meta_path = workdir / "meta.json"
        
        if not audio_path.exists():
            raise FileNotFoundError(f"workdir 中缺少 audio.wav: {workdir}")
        
        # 检查 meta.json 是否存在
        if not meta_path.exists():
            meta_path = None
        
        # 生成 job_id 和 rel_key
        rel_key = str(workdir.name)
        job_id = f"job_{stable_hash(str(workdir.resolve()))}"
        
        # 确定输出目录
        if out_mode == "in_place":
            out_dir = workdir / "seg"
        else:  # out_root
            out_dir = out_root / sanitize_path_component(workdir.name) / "seg"
        
        warnings = []
        if meta_path is None:
            warnings.append("meta.json 不存在")
        
        job = SegJob(
            job_id=job_id,
            input_type="workdir",
            workdir=workdir,
            audio_path=audio_path,
            meta_path=meta_path,
            out_dir=out_dir,
            rel_key=rel_key,
            warnings=warnings,
        )
        return [job]
    
    def _resolve_root(self, root: Path, out_root: Path, out_mode: str) -> list[SegJob]:
        """解析批处理根目录（递归扫描所有 audio.wav）"""
        root = root.resolve()
        jobs = []
        
        # 递归查找所有匹配的文件
        audio_files = sorted(root.rglob(self.pattern))
        
        if not audio_files:
            logger.warning(f"在根目录中未找到任何 {self.pattern} 文件: {root}")
            return []
        
        for audio_path in audio_files:
            audio_path = audio_path.resolve()
            # 判断是否在 workdir 中
            parent = audio_path.parent
            workdir = parent if audio_path.name == "audio.wav" else None
            
            meta_path = None
            if workdir:
                meta_path_candidate = workdir / "meta.json"
                if meta_path_candidate.exists():
                    meta_path = meta_path_candidate
            
            # 生成 rel_key（相对于 root 的路径）
            try:
                rel_key = str(audio_path.relative_to(root).parent)
                if not rel_key or rel_key == ".":
                    rel_key = audio_path.stem
            except ValueError:
                rel_key = audio_path.stem
            
            job_id = f"job_{stable_hash(str(audio_path.resolve()))}"
            
            # 确定输出目录
            if out_mode == "in_place" and workdir:
                out_dir = workdir / "seg"
            else:  # out_root 模式，或单文件
                # 使用相对路径创建镜像目录
                if rel_key and rel_key != ".":
                    out_dir = out_root / sanitize_path_component(rel_key) / "seg"
                else:
                    out_dir = out_root / sanitize_path_component(audio_path.stem) / "seg"
            
            warnings = []
            if workdir and meta_path is None:
                warnings.append("meta.json 不存在")
            
            job = SegJob(
                job_id=job_id,
                input_type="root" if not workdir else "workdir",
                workdir=workdir,
                audio_path=audio_path,
                meta_path=meta_path,
                out_dir=out_dir,
                rel_key=rel_key,
                warnings=warnings,
            )
            jobs.append(job)
        
        return jobs
    
    def _resolve_manifest(self, manifest_path: Path, out_root: Path, out_mode: str) -> list[SegJob]:
        """解析 manifest.jsonl 文件"""
        manifest_path = manifest_path.resolve()
        jobs = []
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"manifest.jsonl 第 {line_num} 行 JSON 解析失败: {e}")
                    continue
                
                # 判断是否成功
                is_success = self._check_success(obj)
                if not is_success:
                    logger.debug(f"manifest.jsonl 第 {line_num} 行标记为失败，跳过")
                    continue
                
                # 解析 workdir
                workdir = self._extract_workdir(obj)
                
                # 解析音频路径
                audio_path = self._extract_audio_path(obj, workdir)
                if audio_path is None:
                    logger.warning(f"manifest.jsonl 第 {line_num} 行无法解析音频路径，跳过")
                    continue
                
                if not audio_path.exists():
                    logger.warning(f"manifest.jsonl 第 {line_num} 行音频文件不存在: {audio_path}，跳过")
                    continue
                
                audio_path = audio_path.resolve()
                
                # 解析 meta.json 路径
                meta_path = self._extract_meta_path(obj, workdir)
                if meta_path and not meta_path.exists():
                    meta_path = None
                
                # 生成 job_id 和 rel_key
                if workdir:
                    rel_key = str(workdir.name)
                    job_id = f"job_{stable_hash(str(workdir.resolve()))}"
                else:
                    rel_key = audio_path.stem
                    job_id = f"job_{stable_hash(str(audio_path.resolve()))}"
                
                # 确定输出目录
                warnings = []
                if out_mode == "in_place" and workdir:
                    out_dir = workdir / "seg"
                else:  # out_root 模式
                    if workdir:
                        out_dir = out_root / sanitize_path_component(workdir.name) / "seg"
                    else:
                        out_dir = out_root / sanitize_path_component(audio_path.stem) / "seg"
                
                if meta_path is None and workdir:
                    warnings.append("meta.json 不存在")
                if workdir is None:
                    warnings.append("无法解析 workdir，使用音频文件名作为键")
                
                job = SegJob(
                    job_id=job_id,
                    input_type="manifest",
                    workdir=workdir,
                    audio_path=audio_path,
                    meta_path=meta_path,
                    out_dir=out_dir,
                    rel_key=rel_key,
                    warnings=warnings,
                )
                jobs.append(job)
        
        return jobs
    
    def _check_success(self, obj: dict) -> bool:
        """检查 JSON 对象是否表示成功
        
        策略：
        - 若存在 status 字段，status in {"success","ok","done"} 视为成功
        - 或存在 ok=true
        - 否则默认成功（为了兼容），但如果存在 error 字段且非空则视为失败
        """
        # 检查 status 字段
        if "status" in obj:
            status = str(obj["status"]).lower()
            if status in ["success", "ok", "done"]:
                return True
            return False
        
        # 检查 ok 字段
        if "ok" in obj:
            return bool(obj["ok"])
        
        # 默认成功，但如果有 error 字段且非空则失败
        if "error" in obj and obj["error"]:
            return False
        
        return True
    
    def _extract_workdir(self, obj: dict) -> Optional[Path]:
        """从 JSON 对象中提取 workdir 路径"""
        # 优先读取 obj["output"]["workdir"] 或 obj["workdir"]
        if "output" in obj and isinstance(obj["output"], dict):
            if "workdir" in obj["output"]:
                return Path(obj["output"]["workdir"])
            if "dir" in obj["output"]:
                return Path(obj["output"]["dir"])
        
        if "workdir" in obj:
            return Path(obj["workdir"])
        
        if "output_dir" in obj:
            return Path(obj["output_dir"])
        
        return None
    
    def _extract_audio_path(self, obj: dict, workdir: Optional[Path]) -> Optional[Path]:
        """从 JSON 对象中提取音频路径"""
        # 优先 obj["output"]["audio_wav"] 或 obj["audio_wav"] 或 obj["audio_path"]
        if "output" in obj and isinstance(obj["output"], dict):
            if "audio_wav" in obj["output"]:
                return Path(obj["output"]["audio_wav"])
            if "audio_path" in obj["output"]:
                return Path(obj["output"]["audio_path"])
        
        if "audio_wav" in obj:
            return Path(obj["audio_wav"])
        
        if "audio_path" in obj:
            return Path(obj["audio_path"])
        
        # 否则若有 workdir：用 workdir/audio.wav
        if workdir:
            return workdir / "audio.wav"
        
        return None
    
    def _extract_meta_path(self, obj: dict, workdir: Optional[Path]) -> Optional[Path]:
        """从 JSON 对象中提取 meta.json 路径"""
        # 优先 obj["output"]["meta_json"] 或 obj["meta_json_path"]
        if "output" in obj and isinstance(obj["output"], dict):
            if "meta_json" in obj["output"]:
                return Path(obj["output"]["meta_json"])
            if "meta_json_path" in obj["output"]:
                return Path(obj["output"]["meta_json_path"])
        
        if "meta_json_path" in obj:
            return Path(obj["meta_json_path"])
        
        # 否则 workdir/meta.json
        if workdir:
            return workdir / "meta.json"
        
        return None

