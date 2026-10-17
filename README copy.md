# tseda: EDA thích ứng cho dữ liệu bảng

`tseda` tự động hóa phần lặp lại của EDA trên các bảng có lẫn số, category, văn bản, ngày, cờ và ID.
Framework **không giả định lĩnh vực**: nó suy ra vai trò của từng cột từ bằng chứng dữ liệu, chọn phương pháp
thống kê theo vai trò đó, và chỉ bật phân tích chuỗi thời gian / panel / phân cấp / ràng buộc khi dữ liệu có cấu trúc đó.

Nguyên tắc: **đề xuất, không tự quyết.** Framework không tự xóa outlier, không tự gộp category, không tự điền missing.
Mọi biến đổi nằm trong `TransformPlan` để người dùng duyệt, áp dụng và xuất ra file để kiểm toán.

## Cài đặt

```bash
pip install -e ".[all]"          # đầy đủ: statsmodels, sqlalchemy, pyarrow, openpyxl, pytest
pip install -e .                 # tối thiểu: pandas, numpy, scipy, matplotlib, pyyaml
```

Ghi chú: `statsmodels` cần cho ADF/KPSS. Thiếu thì phần tính dừng bị bỏ qua và báo lý do, không gây lỗi.

## Bắt đầu nhanh

```python
from tseda import EDA

report = EDA("data.csv", out_dir="out/eda", domain="banking").run()

report.print_summary()              # vai trò, capability bật, phát hiện
report.summary()                    # đếm theo mức CRITICAL / WARN / INFO
report.filter("WARN")               # DataFrame các phát hiện từ WARN trở lên
report.roles_df()                   # vai trò, confidence, phương án khác
report.relations_df()               # kiểm định cặp, effect size, q-value sau BH
report.to_html("out/eda/report.html")

report.plan.summary()               # các đề xuất biến đổi
report.plan.accept(["to_missing:gia_dong:1", "parse_numeric:gia_mo:1"])
cleaned, logs = report.apply_plan() # chỉ áp dụng các bước đã chấp nhận
report.save("out/eda")              # HTML, JSON, CSV, transform_plan.yaml
```

Nguồn đầu vào được hỗ trợ:

| Nguồn | Cách dùng |
|---|---|
| CSV / TSV / TXT | `EDA("x.csv")`, tự sniff encoding (UTF-8, cp1258, UTF-16...) và delimiter |
| JSON / JSONL | `EDA("x.json")`, các trường lồng được flatten thành `a.b` |
| Parquet, Excel | `EDA("x.parquet")`, `EDA("x.xlsx")` |
| SQL | `EDA("postgresql://...", query="select ...")` hoặc `EDA("q.sql", connection="...")` |
| DataFrame | `EDA(df)` |

## Dùng từ dòng lệnh

```bash
tseda profile data.csv --out out/eda --domain banking --config configs/example.yaml --schema configs/example_schema.yaml
tseda profile "postgresql://u:p@host/db" --query "select * from giao_dich" --out out/eda
tseda profile data.csv --stages typing,quality,profile --quiet
tseda profile data.csv --out out/eda --fail-on-critical      # thoát mã 2 nếu có CRITICAL (dùng trong CI)

tseda plan apply --plan out/eda/transform_plan.yaml --input data.csv --out cleaned.csv --accept safe
tseda domains
```

## Dashboard tương tác

`report.save(out)` và `tseda profile` đều tạo `dashboard.html`: một file HTML duy nhất, không cần mạng hay CDN, mở bằng trình duyệt.

```python
report.to_dashboard("out/eda/dashboard.html")
```

Nội dung:

- **Tổng quan:** chỉ số toàn bảng, tỷ lệ thiếu theo cột, số cột theo loại, lưới biểu đồ thu nhỏ cho từng cột (nhấn để mở chi tiết).
- **Bộ lọc:** một hàng phía trên, áp dụng cho mọi phần. Cột phân loại có dropdown, cột số có khoảng min/max, cột ngày có khoảng từ/đến.
- **Biến:** chi tiết một cột kèm thống kê. Số có histogram, phân loại có thanh ngang, ngày có chuỗi theo kỳ.
- **Quan hệ:** ma trận tương quan Spearman tính trên dữ liệu đang lọc, và bảng kiểm định cặp đã hiệu chỉnh BH.
- **Thời gian:** chuỗi theo kỳ (ngày/tháng/năm được chọn tự động theo độ dài dữ liệu). Có thể tách theo thực thể, tối đa `dashboard.series_max` đường, phần còn lại gộp "Khác".
- **Phát hiện:** lọc theo mức độ CRITICAL, WARN, INFO.
- **Bảng dữ liệu:** xem trước và tải CSV của dữ liệu đang lọc.

Lưu ý quan trọng:

- Dashboard **nhúng một mẫu** tối đa `dashboard.max_rows` dòng (mặc định 3000), lấy ngẫu nhiên có seed cố định. Thanh trạng thái luôn ghi rõ khi đang dùng mẫu. Số liệu toàn bảng vẫn nằm trong báo cáo HTML và JSON.
- Mỗi biểu đồ có bảng dữ liệu đi kèm (mục "Xem dạng bảng"). Tooltip cũng hiện khi lấy focus bằng bàn phím.
- Giao diện sáng/tối theo hệ điều hành, có nút chuyển thủ công. Bảng màu lấy từ palette đã kiểm tra bằng `validate_palette.js`.
- Cấu hình nằm trong section `dashboard:` của `default_config.yaml`.

## Luồng xử lý

| Stage | Làm gì | Module |
|---|---|---|
| `typing` | Làm sạch chuỗi sentinel (`N/A`, `chưa có`...), suy vai trò, ép kiểu | `infer/` |
| `quality` | Dòng trùng, cột trùng nội dung, cỡ mẫu, tên cột | `quality/` |
| `profile` | Profile theo vai trò: thống kê robust, mẫu ký tự, biến thể, ngày bất thường... | `profile/` |
| `relate` | Kiểm định theo cặp họ, hiệu chỉnh Benjamini-Hochberg, VIF | `relate/` |
| `capability` | Chỉ bật khi có cấu trúc tương ứng: `temporal`, `panel`, `hierarchy`, `constraints` | `capability/` |
| `transform` | Sinh đề xuất biến đổi có lý do và tác động ước tính | `transform/` |
| `viz` | Biểu đồ chọn theo vai trò cột | `viz/` |

Lỗi ở một stage được ghi vào `report.stage_errors`, các stage khác vẫn chạy.

### Vai trò được suy ra

`EMPTY`, `CONSTANT`, `BOOLEAN`, `ID`, `DATETIME`, `NUMERIC_CONTINUOUS`, `NUMERIC_COUNT`,
`NUMERIC_STORED_AS_TEXT`, `CATEGORICAL_NOMINAL`, `CATEGORICAL_ORDINAL`, `TEXT_SHORT`, `TEXT_FREE`,
`STRUCTURED_TEXT` (email, URL, SĐT, MST, JSON), `MIXED`.

Mỗi cột có `confidence`, danh sách phương án khác và bằng chứng (ví dụ tỷ lệ parse, định dạng ngày).
Cột có hai ứng viên sát điểm nhau sẽ có confidence thấp và được báo cáo để người dùng xác nhận.
Tên cột chỉ cộng một chút điểm; không bao giờ quyết định một mình.

### Điểm đặc thù của dữ liệu Việt Nam

- Số kiểu `23.500` (nghìn) và `1,5` (thập phân), `1.5tr`, `2 tỷ`, `(1.200)`. Locale được bỏ phiếu theo cả cột.
- Ngày `dd/mm/yyyy`. Nếu mọi ngày đều ≤ 12 thì không xác định được thứ tự: framework đánh dấu `ambiguous` và dùng `general.dayfirst`.
- Biến thể tên: `Hà Nội` / `Ha Noi` / `HÀ NỘI` / `Hà  Nội` là cùng một nhóm (đề xuất, không tự gộp). Chuẩn hóa NFC.
- Phát hiện mojibake (UTF-8 bị đọc sai bảng mã) và ký tự Unicode lạ.
- Lịch giao dịch: ngày thiếu được tính theo ngày làm việc. Ngày nghỉ khai báo trong `temporal.holidays` không bị báo thiếu.

### Capability chỉ bật khi có cấu trúc

| Capability | Điều kiện | Kiểm tra |
|---|---|---|
| `temporal` | Có cột ngày đủ dữ liệu | Ngày thiếu theo lịch, timestamp trùng, chuỗi đóng băng, xu hướng (Kendall), tính dừng (ADF+KPSS), mùa vụ (ACF), điểm đứt gãy ứng viên |
| `panel` | Có thời gian và cột thực thể lặp lại | Số thực thể, lịch sử ngắn, khóa (thực thể, thời gian) trùng, thực thể thiếu nhiều |
| `hierarchy` | Có ≥2 cột phân loại | Phụ thuộc hàm `con → cha`, số dòng vi phạm tối thiểu |
| `constraints` | Có ràng buộc từ plugin hoặc cấu hình | Miền giá trị, không âm, đẳng thức, tích `a×b=c`, thứ tự `a≤b`, khóa, điều kiện kéo theo |

Cột thực thể được chọn là cột mà cặp (thực thể, thời gian) gần như duy nhất. Các biến thể cùng khóa chuẩn hóa (khác dấu, hoa thường, khoảng trắng, ví dụ `Hà Nội` / `Ha Noi`) được gộp thành một thực thể ở cả `temporal`, `panel` và dashboard. Nhóm chỉ gần giống theo khoảng cách chuỗi (lỗi gõ) chỉ được đề xuất, không tự gộp. Cột phân nhóm như chi nhánh bị loại tự động.
Có thể ghi đè bằng `general.entity_column` và `general.time_column`.

### Thống kê: chọn theo điều kiện, luôn có effect size

| Cặp họ | Kiểm định | Effect size |
|---|---|---|
| số × số | Spearman | rho |
| số × category | ANOVA nếu nhóm đủ lớn, gần chuẩn, phương sai đồng đều; ngược lại Kruskal-Wallis | eta², epsilon² |
| category × category | Chi-square; Fisher khi bảng 2×2 thưa | Cramér's V có hiệu chỉnh |
| cờ × số | Mann-Whitney | rank-biserial |
| ngày × số | Kendall tau theo trục thời gian | tau |

Level hiếm được gộp thành `__khác__` trước khi kiểm định. Toàn bộ p-value được hiệu chỉnh Benjamini-Hochberg.
Chuỗi thời gian: ADF và KPSS dùng cửa sổ 2.000 quan sát gần nhất (tối đa 3 cột). Điểm đứt gãy có hiệu chỉnh AR(1) và Bonferroni.

## Cấu hình

Mọi ngưỡng nằm trong `tseda/core/default_config.yaml`. Ghi đè bằng file YAML (xem `configs/example.yaml`):

```python
EDA("data.csv", config="configs/example.yaml")
EDA("data.csv", config={"numeric": {"locale": "vi"}, "temporal": {"holidays": ["2024-04-30"]}})
```

Khai báo vai trò thủ công (xem `configs/example_schema.yaml`) ghi đè suy luận, `confidence = 1.0`, `source = schema`:

```python
EDA("data.csv", schema={"so_tien": "numeric_stored_as_text", "ma_gd": "id"})
```

## Plugin domain

Plugin chỉ cung cấp **từ điển tên cột** và **ràng buộc**. Không có plugin thì core vẫn chạy đầy đủ.
Có sẵn: `banking`, `finance`, `retail`.

Viết plugin mới:

```python
from tseda.core.registry import register_domain
from tseda.domain.base import DomainPlugin, find_columns

@register_domain("insurance")
class InsuranceDomain(DomainPlugin):
    name = "insurance"

    def name_hints(self):
        return {"numeric": ["phi_bao_hiem", "boi_thuong"], "categorical": ["san_pham"]}

    def constraints(self, columns, roles):
        phi = find_columns(columns, "phi_bao_hiem")
        boi = find_columns(columns, "boi_thuong")
        rules = [{"type": "nonnegative", "column": c} for c in phi + boi]
        if phi and boi:
            rules.append({"type": "order", "lower": boi[0], "upper": phi[0] + "_max", "name": "bồi thường <= phí"})
        return rules
```

Đăng ký plugin trong `tseda/domain/__init__.py` (import để kích hoạt decorator).

## Mở rộng core

Mỗi analyzer được đăng ký qua decorator, pipeline không cần sửa:

| Muốn thêm | Decorator | Chữ ký hàm |
|---|---|---|
| Profile cho một vai trò | `@register_profiler(Role.X)` | `fn(ctx, name, typed, guess, info) -> dict` |
| Kiểm định cho một cặp họ | `@register_pair("family_a", "family_b")` | `fn(ctx, col_a, col_b, s_a, s_b) -> PairRelation \| None` |
| Capability mới | `@register_capability("ten")` | `fn(ctx) -> dict \| None` (None = không bật) |
| Đề xuất biến đổi | `@register_advisor` | `fn(ctx) -> list[TransformStep]` |
| Phép biến đổi | thêm vào `transform/ops.py` và `OPS` | `fn(series, **params) -> series` |

## Cấu trúc thư mục

```
tseda/
├── pyproject.toml
├── configs/                  # ví dụ cấu hình và khai báo schema
├── examples/quickstart.py
├── tseda/
│   ├── core/                 # config, table, roles, finding, registry, context, pipeline, result
│   ├── io/                   # CSV/JSON/Parquet/Excel/SQL
│   ├── text/                 # chuẩn hóa tiếng Việt, parse số, parse ngày, mẫu ký tự
│   ├── infer/                # làm sạch, thống kê cột, chấm điểm vai trò, ép kiểu
│   ├── profile/              # profile theo vai trò
│   ├── stats/                # hàm thống kê thuần (không biết vai trò)
│   ├── relate/               # kiểm định cặp, BH, VIF
│   ├── quality/              # kiểm tra cấp bảng
│   ├── capability/           # temporal, panel, hierarchy, constraints
│   ├── transform/            # plan, ops, advisor
│   ├── viz/                  # biểu đồ theo vai trò
│   ├── report/               # báo cáo HTML tự chứa
│   ├── dashboard/            # dashboard tương tác: payload, render, assets (css/js/html)
│   ├── domain/               # plugin: banking, finance, retail
│   └── cli.py
└── tests/                    # fixtures có lỗi cố ý + 102 test
```

## Kiểm thử

```bash
pytest
```

`tests/fixtures.py` sinh bảng ngân hàng mô phỏng có các lỗi đã biết trước (chuỗi thiếu ngày, chuỗi đóng băng, vi phạm OHLC,
dòng trùng, biến thể tên chi nhánh, cột hỗn hợp, sentinel, phân cấp). Các test kiểm tra framework phát hiện đúng từng lỗi
và không báo động giả (ví dụ không báo đứt gãy trên chuỗi giá random walk).

## Hiệu năng

Đo trên máy thử (CPU đơn luồng): 50.000 dòng khoảng 6 giây, 200.000 dòng khoảng 17 giây (15 cột, có chuỗi thời gian và panel).
Phần nặng nhất là ADF và biểu đồ; cả hai đã được giới hạn.

## Giới hạn cần biết

- Suy luận vai trò là **heuristic có bằng chứng**. Với cột lạ hoặc confidence thấp, hãy khai báo `schema`.
- Phát hiện đứt gãy là **ứng viên**, không phải kết luận nhân quả. Cần đối chiếu với sự kiện thực tế.
- Gộp biến thể dựa trên khoảng cách chuỗi có thể gộp nhầm hai tên rất giống nhau. Vì vậy chỉ đề xuất.
- Mẫu cho kiểm định: bảng vượt `general.max_n_for_tests` được lấy mẫu ngẫu nhiên có seed cố định.
- Text tự do chỉ có thống kê mẫu ký tự, độ dài, ngôn ngữ. NLP sâu (topic, embedding) chưa có.
- Chưa có chế độ hoàn tác (undo) cho transform plan. Luôn giữ dữ liệu gốc và dùng `apply_plan` trên bản sao.
