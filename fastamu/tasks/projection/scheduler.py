from taskiq import ScheduleSource, TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from fastamu.tasks.projection.broker import broker, repair_config, retry_source

if retry_source is None and repair_config is None:
    raise RuntimeError(
        "Configure projection retry or repair for the scheduler"
    )

sources: list[ScheduleSource] = [LabelScheduleSource(broker)]
if retry_source is not None:
    sources.append(retry_source)
scheduler = TaskiqScheduler(broker, sources=sources)
