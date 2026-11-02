# CLAUDE.md

## Mục tiêu
CLI Python tổng hợp `ad_data.csv` (~1GB, ~26,8 triệu dòng, 50 campaign) theo `campaign_id`,
ghi `top10_ctr.csv` (CTR cao nhất) và `top10_cpa.csv` (CPA thấp nhất). Đề: FV-SEC001 Ad Performance
Aggregator. Chấm theo: đúng kết quả, code sạch, xử lý lỗi, hiệu năng/RAM, test, README ghi quyết định.

## Cấu trúc
- `aggregator.py` — toàn bộ logic và CLI (chỉ thư viện chuẩn)
- `tests/test_aggregator.py` — pytest; `pytest.ini`, `requirements-dev.txt`
- `scripts/inspect_data.py` — khảo sát dữ liệu, chỉ in tóm tắt
- `results/` — output sinh ra từ chương trình; `data/` — input (git bỏ qua)
- `Dockerfile`, `README.md`, `PROMPTS.md` (prompt của người dùng, ghi nguyên văn)

## Lệnh (Windows PowerShell)
- Chạy: `python aggregator.py --input data\ad_data.csv --output results` (nhận cả `.zip`)
- Test: `python -m pytest`
- Khảo sát dữ liệu: `python scripts\inspect_data.py`
- Benchmark: `python scripts\benchmark.py --input data\ad_data.csv` (ghi vào `benchmark.log`; chỉ đo tiến trình chính)
- Verify: so output với một phép gộp độc lập (DuckDB, DECIMAL + Fraction). Chưa có script trong repo;
  ghi output ra thư mục tạm, không ghi vào `results/`.

## Quy tắc cứng
1. Không mở, đọc, `head`, in nội dung `data/ad_data.csv`. Chỉ chương trình trong repo được stream nó.
2. Không sửa `results/` bằng tay; chỉ sinh lại bằng cách chạy `aggregator.py`.
3. `aggregator.py` chỉ dùng thư viện chuẩn (pytest chỉ cho test).
4. Không dead code, không code bị comment. Tên biến/hàm rõ nghĩa.
5. Mỗi thay đổi phải chạy `python -m pytest` và báo kết quả thật.
6. Môi trường là Windows PowerShell: dùng cú pháp PowerShell, đường dẫn `\`.
7. Diff nhỏ, không refactor ngoài phạm vi yêu cầu.
8. Hỏi người dùng trước khi đổi bất kỳ quyết định thiết kế nào bên dưới.
9. Mỗi prompt của người dùng được thêm vào `PROMPTS.md`.

## Quyết định thiết kế đã duyệt
- 4 worker cố định (process), WORKERS*4 khoảng byte; khoảng sở hữu mọi dòng BẮT ĐẦU trong nó;
  hỗ trợ `.csv` và `.zip` (giải nén ra thư mục tạm).
- CTR = tổng clicks / tổng impressions, CPA = tổng spend / tổng conversions, kiểu `Fraction`.
- Xếp hạng trên giá trị chính xác, tie-break theo `campaign_id` tăng dần; chỉ làm tròn khi ghi
  (half up): CTR 4 chữ số, CPA và total_spend 2 chữ số.
- Spend đọc thành số nguyên 1e-6 USD (tối đa 6 chữ số thập phân), không dùng float.
- impressions = 0 hoặc conversions = 0: giữ campaign, ô CTR/CPA trống, chỉ bỏ khỏi bảng xếp hạng
  của chỉ số đó.
- Dòng lỗi (sai số cột, không phải số, số âm, id rỗng) bị bỏ qua và đếm; header sai thì dừng (exit 1).
- Chấp nhận BOM UTF-8, CRLF, trường có nháy (trừ khi ranh giới khoảng cắt giữa trường nhiều dòng), cột đổi thứ tự.
