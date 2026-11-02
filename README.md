# Ad Performance Aggregator

Lời giải cho bài thử thách FV-SEC001 *Ad Performance Aggregator*: đọc tệp `ad_data.csv` (~1 GB,
26.843.544 dòng, 50 campaign), gộp theo `campaign_id` và ghi ra hai tệp:

- `top10_ctr.csv`: 10 campaign có CTR cao nhất (CTR = clicks / impressions);
- `top10_cpa.csv`: 10 campaign có CPA thấp nhất (CPA = spend / conversions).

Cả hai tệp có các cột `campaign_id,total_impressions,total_clicks,total_spend,total_conversions,CTR,CPA`.
`total_spend` và `CPA` lấy 2 chữ số thập phân, `CTR` lấy 4 chữ số, đúng như bảng mẫu của đề.

## 1. Hướng dẫn cài đặt

Yêu cầu: **Python 3.14** trên Windows 10 (phiên bản dùng để phát triển và đo đạc).
Chạy chương trình chính **không cần cài thêm gói nào** vì chỉ dùng thư viện chuẩn.

```powershell
git clone https://github.com/huongdoan-hugo/ad-data-aggregator.git
cd ad-data-aggregator

# Tùy chọn: môi trường ảo, chỉ cần khi chạy test và script kiểm chứng
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt      # pytest, duckdb
```

Đặt dữ liệu vào `data\ad_data.csv` (thư mục `data\` không được đưa lên git). Có thể dùng trực tiếp
tệp `.zip` gốc mà không cần giải nén.

## 2. Cách chạy chương trình

```powershell
python aggregator.py --input data\ad_data.csv --output results
python aggregator.py --input ad_data.csv.zip --output results
```

| Tham số | Ý nghĩa |
|---|---|
| `--input` | Tệp `.csv`, hoặc `.zip` chứa đúng một tệp `.csv`. Loại tệp được nhận diện theo nội dung, không theo đuôi. Tệp zip được giải nén vào thư mục tạm (cần dung lượng trống bằng cỡ tệp CSV) và xóa sau khi chạy xong. |
| `--output` | Thư mục ghi hai tệp kết quả. Tự tạo nếu chưa có (kể cả thư mục cha); tệp kết quả cũ bị ghi đè. |

Số tiến trình song song cố định là 4 (xem mục Quyết định thiết kế). Khi thành công, chương trình in:

```
Read 26843544 data rows, 50 campaigns.
Skipped 0 bad rows {}.
Wrote top10_ctr.csv and top10_cpa.csv to results
```

Mã thoát: `0` thành công; `1` đầu vào không xử lý được (không tìm thấy, rỗng, zip hỏng, header sai,
dòng dài hơn 64 KiB) hoặc không ghi được kết quả; `2` tham số không hợp lệ.
Lỗi luôn được in ra stderr dưới dạng một dòng `error: ...`, không bao giờ là traceback.

### Chạy bằng Docker

```powershell
docker build -t ad-aggregator .
docker run --rm -v "${PWD}\data:/data" -v "${PWD}\results:/results" ad-aggregator
```

`.dockerignore` chỉ cho phép `aggregator.py` vào build context nên thư mục `data\` 1 GB không bị gửi
cho Docker daemon. Image **chưa được build và chạy thử** vì máy phát triển không cài Docker.

### Các script đi kèm

| Script | Công dụng |
|---|---|
| `scripts\verify_with_duckdb.py` | Tính lại tổng từ `data\ad_data.csv` bằng DuckDB (cộng DECIMAL chính xác), xếp hạng bằng `Fraction`, rồi so với `results\` (thứ tự, các cột số nguyên, `total_spend`, `CTR`, `CPA`). In `MATCH` (thoát 0) hoặc từng chỗ lệch (thoát 1). Độc lập với `aggregator.py`. |
| `scripts\benchmark.py` | Chạy `aggregator.py` trong tiến trình riêng, ghi thời gian, bộ nhớ đỉnh, cấu hình máy và kết quả chạy vào `benchmark.log`. Chỉ chạy trên Windows. |
| `scripts\inspect_data.py` | Đọc streaming một lượt và in tóm tắt chất lượng dữ liệu (vài dòng đầu, số dòng, số campaign, dòng lỗi, khoảng giá trị, dấu nháy). |

### Chạy kiểm thử

```powershell
python -m pytest
```

100 test, khoảng 1.5 giây. Bao gồm: phân tích dòng và từng loại dòng lỗi, cộng spend chính xác,
CTR/CPA và giá trị không xác định, xếp hạng (giảm/tăng, tối đa 10, tie-break, hai giá trị mà `float`
không phân biệt được), làm tròn half-up, định dạng đầu ra, header/BOM/CRLF, trường có dấu nháy, đầu vào
zip, lỗi đầu vào, và song song: các khoảng byte phủ mọi dòng đúng một lần với nhiều số khoảng khác nhau
(LF, CRLF, thiếu newline cuối, chỉ có header, có dòng lỗi và dòng trống), cùng một lần chạy qua `Pool`
4 worker thật so với bảng kết quả mong đợi do chính test tự tính.

## 3. Thư viện được sử dụng

- **`aggregator.py` chỉ dùng thư viện chuẩn của Python:** `argparse`, `collections`, `contextlib`,
  `csv`, `fractions`, `heapq`, `multiprocessing`, `os`, `re`, `shutil`, `sys`, `tempfile`, `typing`,
  `zipfile`, `zlib`.
- Các script chỉ dùng thư viện chuẩn (`benchmark.py` dùng thêm `ctypes` để gọi API Windows), riêng
  `verify_with_duckdb.py` dùng `duckdb`.
- Kiểm thử: `pytest`.

## 4. Thời gian xử lý tệp 1GB

Đo bằng `python scripts\benchmark.py --input data\ad_data.csv`; các bản ghi gốc nằm trong
`benchmark.log`. Máy đo: Windows 10, CPU Intel 6 nhân / 12 luồng, RAM 15.9 GB, Python 3.14.10.
Tệp nằm sẵn trong bộ nhớ đệm của hệ điều hành, 4 worker, 16 khoảng byte, không có tải nào khác.

| Lần đo | Thời gian |
|---|---|
| 1 | 40.49 s |
| 2 | 40.21 s |
| 3 | 38.22 s |
| **Trung vị** | **40.21 s** |

Ba bản ghi đầu trong `benchmark.log` (khoảng 37 s) được đo trước các thay đổi cuối về độ bền
(giới hạn độ dài dòng, xử lý dấu nháy lạc); ba bản ghi sau là của mã được nộp.

Kết quả đã được đối chiếu với phép tính độc lập bằng DuckDB: **MATCH**. Với dữ liệu này, cả 10 giá trị CTR
trong `top10_ctr.csv` đều hiển thị `0.0275`, nên thứ tự do phân số chính xác và tie-break theo
`campaign_id` quyết định, không phải giá trị đã làm tròn.

## 5. Mức sử dụng bộ nhớ đỉnh

Đã đo, cùng ba lần chạy ở trên:

| Lần đo | Peak commit, cả cây tiến trình (tiến trình chính + 4 worker) | Peak working set, chỉ tiến trình chính |
|---|---|---|
| 1 | 75.4 MB | 21.4 MB |
| 2 | 74.9 MB | 21.1 MB |
| 3 | 74.7 MB | 21.1 MB |
| **Lớn nhất** | **75.4 MB** | 21.4 MB |

- **Con số dùng cho cả lần chạy là cột peak commit (~75 MB).** Nó được đọc từ job object của Windows,
  nên gồm cả 4 worker. Commit là bộ nhớ riêng đã cấp phát, không đồng nhất với working set; cột working
  set chỉ phản ánh tiến trình chính và không gồm các worker.
- Bộ nhớ không tăng theo kích thước tệp: mỗi worker đọc từng dòng trong khoảng của mình và chỉ giữ một
  bộ tổng nhỏ cho mỗi campaign. Bộ nhớ tăng theo số campaign *khác nhau*, không theo số dòng.
- Một dòng dài hơn 64 KiB bị từ chối (xem bảng dưới) để mỗi worker không bao giờ phải nạp một dòng
  khổng lồ vào bộ nhớ.

## 6. Quyết định thiết kế

Đề bài để ngỏ một số điểm. Mỗi dòng dưới đây nêu lựa chọn và lý do.

| Chủ đề | Quyết định | Lý do |
|---|---|---|
| Song song | 4 tiến trình cố định. Phần dữ liệu sau header chia thành `WORKERS * 4` = 16 khoảng byte liên tiếp. Mỗi khoảng sở hữu mọi dòng *bắt đầu* trong nó: worker lùi 1 byte, bỏ nốt phần dòng dở, rồi đọc đến khi dòng kế tiếp bắt đầu ở hoặc sau cuối khoảng. | Mỗi dòng được đếm đúng một lần dù ranh giới cắt ở đâu; 16 khoảng cho 4 worker giúp cân tải. `process_range` là hàm cấp module nên chạy đúng với `spawn` của Windows. |
| Tệp nhỏ | Mỗi khoảng tối thiểu 1 MiB; tệp dưới 1 MiB đọc trong một khoảng, không tạo pool. | Tránh chi phí khởi động tiến trình, và tệp nhỏ không bị ảnh hưởng bởi ranh giới khoảng. |
| CTR và CPA | Tính một lần cho mỗi campaign từ tổng, kiểu `Fraction`: `sum(clicks)/sum(impressions)` và `sum(spend)/sum(conversions)`. | Trung bình các tỷ lệ từng dòng là sai; giá trị chính xác tránh trôi số thực và hòa giả. |
| Xếp hạng | Trên giá trị chính xác, không bao giờ trên giá trị đã làm tròn. Hòa thì theo `campaign_id` tăng dần. | Kết quả xác định, không phụ thuộc cách chia dòng cho worker. |
| Làm tròn | Chỉ khi ghi file, theo half-up: CTR 4 chữ số, CPA và `total_spend` 2 chữ số. | Khớp bảng mẫu; tránh làm tròn chẵn của Python. |
| Spend | Đọc thành số nguyên đơn vị 1e-6 USD, không dùng float. Chấp nhận tối đa 6 chữ số thập phân; có dấu, dạng mũ hoặc hơn 6 chữ số thì dòng bị loại. | Cộng chính xác; loại dòng an toàn hơn là âm thầm làm tròn tiền. Dữ liệu thật chỉ có tối đa 2 chữ số. |
| CTR/CPA không xác định | Campaign không có impressions (CTR) hoặc không có conversions (CPA) vẫn được giữ; ô không xác định để trống, và campaign chỉ bị bỏ khỏi bảng xếp hạng của chỉ số đó. | Không bỏ dữ liệu âm thầm; tỷ lệ không xác định không bao giờ được xếp hạng. |
| Dòng lỗi | Bị bỏ qua và đếm theo lý do: `wrong_column_count`, `empty_campaign_id`, `negative_value`, `not_a_number`, `spend_over_6_decimals`, `malformed_row`. Số phải là chữ số ASCII thuần, nên `nan`, `inf`, `1e5`, dấu, khoảng trắng và chữ số không phải ASCII đều bị loại. Dòng trống bị bỏ qua. | Một dòng hỏng không được làm mất kết quả của lần chạy 1 GB. |
| `campaign_id` | Cắt khoảng trắng hai đầu; ngoài ra phân biệt hoa thường (`a` khác `A`). Số thì không bị cắt. | Khoảng trắng thừa sẽ âm thầm tách một campaign thành hai; còn ở số thì nó thành một dòng lỗi nhìn thấy được. |
| Header | Phải có `campaign_id, impressions, clicks, spend, conversions` (không phân biệt hoa thường, thứ tự bất kỳ, cho phép cột thừa, cột bị lặp thì từ chối). Không cần, không dùng và không kiểm tra cột `date`. Chấp nhận BOM UTF-8. Header không phải CSV hợp lệ là lỗi đầu vào. | Dừng sớm với tệp không thể diễn giải. |
| Dấu nháy | Dòng chứa `"` được phân tích bằng module `csv`: dấu phẩy và xuống dòng trong nháy hoạt động (một trường có thể trải dài tới 100 dòng). Một dòng nhiều dòng mà không hợp lệ chỉ tốn một dòng: đếm một lần rồi đọc tiếp từ dòng thứ hai, nên một dấu nháy lạc không thể nuốt các dòng phía sau. Trường trong nháy vượt giới hạn của `csv` (128 KB) là `malformed_row`. | Dữ liệu thật không có dấu nháy, nhưng một dấu `"` lạc không được làm mất dữ liệu âm thầm hay làm sập chương trình. |
| Giới hạn của xử lý dấu nháy | Nếu ranh giới giữa hai khoảng rơi vào giữa một trường nháy nhiều dòng, khoảng sau bắt đầu giữa trường và đọc phần còn lại thành dòng lỗi. | Phát hiện trường hợp này cần quét tuần tự, làm mất ý nghĩa của việc chia khoảng. |
| Độ dài dòng | Dòng dài hơn 64 KiB là lỗi đầu vào (thoát 1). | Chặn bộ nhớ mỗi worker; một dòng quảng cáo thật dài khoảng 40 byte, nên dòng như vậy nghĩa là tệp không phải CSV theo dòng (ví dụ kết thúc dòng chỉ bằng `\r`). |
| Kết thúc dòng | Chấp nhận `\n` và `\r\n`. | |
| Đầu vào zip | Giải nén vào thư mục tạm rồi chia khoảng như CSV. Zip phải chứa đúng một `.csv`. | Dữ liệu nén không thể đọc ở vị trí byte tùy ý. |
| Ít hơn 10 campaign | Ghi bấy nhiêu dòng có. Không có dòng hợp lệ nào: tệp chỉ có header, mã thoát 0. | |
| Không kiểm tra | `clicks > impressions` và định dạng `date`. | Đề không coi chúng là lỗi. |
| In ra màn hình | Ký tự mà stdout không mã hóa được (ví dụ trong đường dẫn output qua pipe trên Windows) được thay bằng `?` thay vì làm sập chương trình. | Hai tệp kết quả đã được ghi xong trước khi in tóm tắt. |

## Cấu trúc thư mục

```
aggregator.py               chương trình chính (chỉ dùng thư viện chuẩn)
tests/test_aggregator.py    bộ test pytest
scripts/                    inspect_data.py, verify_with_duckdb.py, benchmark.py
results/                    top10_ctr.csv, top10_cpa.csv sinh từ data\ad_data.csv
benchmark.log               các lần đo (scripts\benchmark.py ghi nối thêm vào)
Dockerfile, .dockerignore   image container
requirements-dev.txt        pytest, duckdb (chỉ cho test và kiểm chứng)
CLAUDE.md                   quy tắc làm việc cho trợ lý AI dùng trong dự án
PROMPTS.md                  các prompt đã dùng
```

## Sử dụng AI

Dự án dùng trợ lý AI lập trình trong suốt quá trình làm; toàn bộ prompt nằm trong
[PROMPTS.md](PROMPTS.md).
