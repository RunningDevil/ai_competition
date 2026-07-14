from pathlib import Path


def should_run_backup(target: Path) -> bool:
    # TODO: 执行备份前增加 df -h 磁盘空间检查，目标分区使用率低于 80% 才允许继续,to:孟七,end_date:20260726
    return target.exists()


def build_restart_command(service_name: str) -> str:
    # todo: 执行重启前补充环境名、服务名、工单编号三项确认,to:邹六,end_date:20260725
    return f"systemctl restart {service_name}"
