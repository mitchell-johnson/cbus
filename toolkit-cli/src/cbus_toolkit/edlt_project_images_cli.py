"""Read-only FILE image export consumed by native eDLT metadata planners."""
from __future__ import annotations

from pathlib import Path

from .native import _project


def prepare(project, output):
    project = _project(project)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Project image export destination already exists')
    if not output.parent.is_dir():
        raise ValueError('Project image export destination directory does not exist')
    return project, output


def export(client, prepared):
    from .edlt_scene_label_images import MAX_EXPORT_BYTES, export_project_images

    project, output = prepared
    result = export_project_images(client, project)
    raw = result.raw
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError('Project image export exceeds its bounded input profile')
    # Exclusive creation also protects against a destination created after
    # preflight. No existing operator file is overwritten.
    with output.open('xb') as stream:
        stream.write(raw)
    return {'format': 'cbus-edlt-project-images-export-v1',
            'project': project, 'output_file': str(output), 'bytes': len(raw),
            'sha256': result.images.export_sha256, 'evidence': result.as_dict(),
            'project_save_requested': False, 'physical_io_requested': False,
            'automatic_retries': 0}
