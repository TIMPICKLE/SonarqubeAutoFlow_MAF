"""CLI 入口 - MAF 版本"""
import argparse
import sys
from orchestrator import main


def cmd_run(args):
    result = main()
    return 0 if result.get("success") else 1


def cmd_status(args):
    from config import Config
    Config.load_total_Effort_time()
    print(f"累计修复耗时: {Config.total_Effort_time} 分钟")
    print(f"GLM 模型: {Config.GLM_MODEL}")
    print(f"GLM Base URL: {Config.GLM_BASE_URL}")
    return 0


def main_cli():
    parser = argparse.ArgumentParser(description="SonarQube 代码异味自动修复系统 (MAF 版)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="执行自动修复流程")
    sub.add_parser("status", help="查看系统状态")
    args = parser.parse_args()
    if args.command == "run":
        return cmd_run(args)
    elif args.command == "status":
        return cmd_status(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main_cli())
