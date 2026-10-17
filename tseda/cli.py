"""Giao diện dòng lệnh.

  tseda profile data.csv --out out/eda [--domain banking] [--config my.yaml] [--schema schema.yaml]
  tseda profile "postgresql://u:p@h/db" --query "select * from t" --out out/eda
  tseda plan apply --plan out/eda/transform_plan.yaml --input data.csv --out cleaned.csv --accept all
  tseda domains
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def _load_schema(path: str | None) -> dict | None:
    if not path:
        return None
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    return {str(k): str(v) for k, v in (data or {}).items()}


def _cmd_profile(args: argparse.Namespace) -> int:
    from tseda import EDA

    stages = [s.strip() for s in args.stages.split(",")] if args.stages else None
    eda = EDA(
        args.input,
        config=args.config,
        schema=_load_schema(args.schema),
        domain=args.domain,
        out_dir=args.out,
        query=args.query,
        connection=args.connection,
        max_rows=args.max_rows,
        encoding=args.encoding,
        sep=args.sep,
    )
    report = eda.run(stages=stages)
    if not args.quiet:
        report.print_summary()
    if args.out:
        written = report.save(args.out)
        if not args.quiet:
            print("\nĐã ghi:")
            for key, path in written.items():
                print(f"  {key}: {path}")
    if args.fail_on_critical and any(f.severity.name == "CRITICAL" for f in report.findings):
        return 2
    return 0


def _cmd_plan_apply(args: argparse.Namespace) -> int:
    from tseda.io.readers import load
    from tseda.transform.plan import TransformPlan

    plan = TransformPlan.load(args.plan)
    if args.accept == "all":
        plan.accept()
    elif args.accept == "safe":
        plan.auto_accept_safe()
    elif args.accept:
        plan.accept([x.strip() for x in args.accept.split(",")])
    table = load(args.input, encoding=args.encoding, sep=args.sep)
    out, logs = plan.apply(table.df)
    if args.out.lower().endswith(".parquet"):
        out.to_parquet(args.out, index=False)
    else:
        out.to_csv(args.out, index=False, encoding="utf-8")
    failed = [log for log in logs if log.status == "failed"]
    applied = [log for log in logs if log.status == "applied"]
    print(f"Đã áp dụng {len(applied)} bước, lỗi {len(failed)}, ghi ra {args.out}")
    for log in failed:
        print(f"  LỖI {log.step_id}: {log.message}", file=sys.stderr)
    return 1 if failed else 0


def _cmd_domains(_: argparse.Namespace) -> int:
    from tseda.domain import available_domains
    for name in available_domains():
        print(name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tseda", description="EDA thích ứng cho dữ liệu bảng.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("profile", help="Chạy EDA và xuất báo cáo")
    pr.add_argument("input", help="file (csv/tsv/json/jsonl/parquet/xlsx), chuỗi kết nối SQL, hoặc file .sql")
    pr.add_argument("--out", help="thư mục xuất báo cáo")
    pr.add_argument("--config", help="file YAML ghi đè cấu hình mặc định")
    pr.add_argument("--schema", help="file YAML/JSON khai báo vai trò thủ công {cột: role}")
    pr.add_argument("--domain", help="plugin domain: banking | finance | retail")
    pr.add_argument("--stages", help="danh sách stage, cách nhau bởi dấu phẩy")
    pr.add_argument("--query", help="câu SQL khi input là chuỗi kết nối")
    pr.add_argument("--connection", help="chuỗi kết nối khi input là file .sql")
    pr.add_argument("--max-rows", type=int, dest="max_rows")
    pr.add_argument("--encoding")
    pr.add_argument("--sep")
    pr.add_argument("--quiet", action="store_true")
    pr.add_argument("--fail-on-critical", action="store_true", dest="fail_on_critical",
                    help="thoát mã 2 nếu có phát hiện CRITICAL (dùng trong CI)")
    pr.set_defaults(func=_cmd_profile)

    pl = sub.add_parser("plan", help="thao tác với transform plan")
    plsub = pl.add_subparsers(dest="plan_cmd", required=True)
    pa = plsub.add_parser("apply", help="áp dụng plan lên file dữ liệu")
    pa.add_argument("--plan", required=True)
    pa.add_argument("--input", required=True)
    pa.add_argument("--out", required=True)
    pa.add_argument("--accept", default="", help="'all', 'safe', hoặc danh sách id cách nhau bởi dấu phẩy")
    pa.add_argument("--encoding")
    pa.add_argument("--sep")
    pa.set_defaults(func=_cmd_plan_apply)

    pd_ = sub.add_parser("domains", help="liệt kê plugin domain")
    pd_.set_defaults(func=_cmd_domains)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
