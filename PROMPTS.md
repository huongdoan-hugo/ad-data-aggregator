# Prompts

1. từ giờ hay ghi tất cả các prompt của t vào file PROMPTS.md

2. Đọc đề bài tại https://github.com/flinters-vietnam/recruitment/blob/main/fv-sec-001-software-engineer-challenge/README.md (nếu không đọc được, tôi sẽ dán nội dung). Chưa viết code. Hãy: tóm tắt yêu cầu bắt buộc, liệt kê sản phẩm phải nộp,  liệt kê tiêu chí chấm,  chép lại hai bảng "Expected output format" để tôi đối chiếu định dạng (tên cột, thứ tự cột, số chữ số thập phân), liệt kê những điểm đề chưa nói rõ mà ta phải tự quyết định (ví dụ impressions = 0, tie-break, giá trị null, dòng lỗi). Trình bày ngắn gọn.

3. cần cung cấp thêm thông tin gì để làm ?

4. 2 bảng theo trong trong link yêu cầu

5. phân tích đề bài và đưa ra giải pháp, thiết kế tối ưu sao cho thời gian ngắn và chính xác yêu cầu

6. Python thuần, đọc theo khối byte, chia cho nhiều process rồi gộp, tính toán chạy bao nhiêu luồng song song để tối ưu nhất

7. phân tích thời gian và peak ram của  từng số lượng luônf

8. Dữ liệu ở data/ad_data.csv (~1GB), tuyệt đối không đọc cả file hay in nhiều dòng. Viết scripts/inspect_data.py chỉ dùng thư viện chuẩn, đọc streaming một lượt và chỉ in tóm tắt: 5 dòng đầu, tổng số dòng, header có đúng 6 cột không, số campaign_id khác nhau, số dòng lỗi (sai số cột, không phải số, số âm), số chữ số thập phân lớn nhất của spend, có trường nào chứa dấu nháy hoặc xuống dòng trong dấu nháy không, số byte trung bình mỗi dòng, min/max các cột số, số dòng có impressions = 0, số campaign có tổng conversions = 0. Chạy script và báo cáo kết quả.

9. Dựa trên đề và kết quả khảo sát dữ liệu, đề xuất thiết kế, chưa viết code

10. viết code 4 luồng song song hỗ trợ cả hai input .zip và .csv, CPA  trống thì loại bỏ , làm dockerfile, CTR và CPA là Fraction và xếp hạng trên giá trị chính xác, chỉ làm tròn khi ghi file theo bảng mẫu của đề (CTR 4 chữ số thập phân, CPA và total_spend 2 chữ số), tie-break theo campaign_id, aggregator.py chỉ dùng thư viện chuẩn. Với mỗi điểm đề chưa rõ, nêu lựa chọn khuyến nghị kèm lý do. Hãy phản biện thiết kế: có rủi ro nào tôi bỏ sót không (spend hơn 2 chữ số thập phân, trường có nháy, file có BOM)? Kết thúc bằng danh sách quyết định để tôi duyệt.

11. CPA trống thì vẫn giữ giá trị không loại bỏ, sử dụng pytest, chưa viết code

12. Tạo CLAUDE.md dưới 60 dòng gồm: mục tiêu, cấu trúc thư mục, lệnh (chạy, test, verify, benchmark), và các quy tắc cứng: không đọc data/ad_data.csv; không sửa results/ bằng tay; aggregator.py chỉ dùng thư viện chuẩn; không dead code ; tên rõ nghĩa; mỗi thay đổi phải chạy pytest; môi trường là Windows PowerShell; diff nhỏ, không refactor ngoài phạm vi; hỏi tôi trước khi đổi bất kỳ quyết định thiết kế nào đã duyệt. Ghi các quyết định thiết kế đã duyệt vào một mục ngắn.

13. Theo các quyết định đã duyệt, viết tests/test_aggregator.py trước khi viết code (pytest, thêm pytest.ini với pythonpath = .). Test cần có: cộng dồn nhiều dòng cùng campaign; spend cộng không sai số; parse_cents hợp lệ và các giá trị bị từ chối; dòng lỗi các loại :sai số cột, không phải số, số âm, spend hơn 2 chữ số, nan, inf được bỏ qua và đếm; dòng trống; header sai; CTR và CPA chính xác, impressions = 0 và conversions = 0 cho giá trị rỗng; xếp hạng giảm/tăng, loại campaign thiếu chỉ số, tối đa 10, tie-break, và một ca hai giá trị mà float không phân biệt được; định dạng làm tròn half-up; ghi file đúng header và định dạng; chạy từ đầu đến cuối. Dùng CSV mẫu nhỏ trong tmp_path. Chưa viết aggregator.py. Cho tôi danh sách test và giải thích mỗi nhóm kiểm tra điều gì.

14. A

15. Viết aggregator.py (một tiến trình, streaming) để mọi test trên đều qua, theo CLAUDE.md. CLI: --input và --output. Hàm nhỏ, tên rõ nghĩa, không dead code, không comment thừa. Chạy pytest -q và báo kết quả. Chưa tối ưu, chưa làm song song.

16. Viết scripts/verify_with_duckdb.py độc lập với aggregator.py: dùng DuckDB tính lại tổng theo campaign từ data/ad_data.csv và so sánh với results/top10_ctr.csv và results/top10_cpa.csv (thứ tự campaign, các cột số nguyên, total_spend, CTR và CPA trong dung sai làm tròn). In MATCH và thoát 0 nếu khớp, ngược lại in từng chỗ lệch và thoát 1. Chỉ script này được dùng DuckDB. Chưa chạy trên file 1GB.

17. Chạy aggregator.py trên data/ad_data.csv, xuất vào results/, rồi chạy scripts/verify_with_duckdb.py. Báo: dòng tóm tắt, thời gian, MATCH hay lệch, và hiển thị hai file kết quả dạng bảng Markdown để tôi đối chiếu với bảng mẫu của đề. Nếu lệch, phân tích nguyên nhân, chưa sửa.

18. .

19. Viết scripts/benchmark.py chỉ dùng thư viện chuẩn, chạy được trên Windows: chạy aggregator trong một tiến trình riêng, đo thời gian và peak memory (dùng ctypes), nối kết quả vào benchmark.log kèm thời điểm, tham số và cấu hình máy. aggregator.py không được import hay phụ thuộc script này. Ghi chú rõ trong script và README giới hạn: khi chạy nhiều worker, cách đo chỉ thấy tiến trình chính.

20. Chuyển aggregator.py sang xử lý song song cố định 4 worker . Chia phần dữ liệu sau header thành WORKERS*4 khoảng byte liên tiếp; mỗi khoảng sở hữu mọi dòng BẮT ĐẦU trong khoảng đó ,lùi 1 byte rồi bỏ nốt phần dòng dở để tìm đầu dòng. Mỗi worker gom riêng bằng cent, tiến trình chính kiểm tra header và gộp kết quả. Phải chạy đúng trên Windows (spawn, hàm worker ở cấp module). Giữ nguyên hành vi và định dạng đầu ra; mọi test cũ vẫn phải qua. Thêm test: chia khoảng không mất hay trùng dòng với nhiều số khoảng khác nhau (gọi trực tiếp hàm xử lý một khoảng, không cần Pool), có CRLF, file thiếu newline cuối, file chỉ có header; và một test chạy qua Pool 4 worker cho kết quả bằng kết quả mong đợi. Chạy pytest -q, chưa chạy trên file 1GB.

21. Chạy scripts/benchmark.py trên data/ad_data.csv 3 lần và ghi vào benchmark.log. Sau đó xóa results/*.csv, chạy aggregator.py để sinh lại kết quả, rồi chạy scripts/verify_with_duckdb.py và báo MATCH hay lệch. Lập bảng so sánh trung vị thời gian của lần đo mốc (một tiến trình) và 4 worker. Nếu lệch, phân tích nguyên nhân, chưa sửa.

22. commit lại các file cần thiết trừ ad_data.csv, .claude
