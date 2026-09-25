# BÁO CÁO CÁ NHÂN – DATA OBSERVABILITY LAB

## 1. Thông tin cá nhân

| Mục | Thông tin |
|---|---|
| Họ tên | **Dương Dương** |
| MSSV | **2A202602498** |
| Khóa/Lớp | **K4** |
| Nhóm | **ThienLyOi** |
| Vai trò | **Pipeline Lead & Integrator** |
| Repository | <https://github.com/Thees-Anh/K4A-Day10-ThienLyOi.git> |
| Nhánh cá nhân | `duongduong` |
| Ngày báo cáo | **2026-09-25** |

## 2. Phạm vi công việc phụ trách

Trong vai trò Pipeline Lead & Integrator, tôi phụ trách điều phối luồng chạy, quản lý cấu hình trong `core/`, kết nối pipeline baseline với corruption/repair flow, và kiểm tra tính tương thích giữa các module do các thành viên phát triển.

Các hạng mục chính đã hoàn thành:

1. Hoàn thiện `src/core/config.py` và `src/core/utils.py`: đọc biến môi trường, quản lý đường dẫn artifact, kiểm tra cấu hình đầu vào, tạo thư mục an toàn và hỗ trợ ghi dữ liệu ổn định.
2. Hoàn thiện luồng baseline trong `src/pipelines/phase1.py`: ingestion → quality/freshness → index → retrieval/evaluation → reporting.
3. Hoàn thiện `src/pipelines/corruption_flow.py`: tạo dữ liệu lỗi có kiểm soát, đo suy giảm, chạy repair, xây dựng lại index và so sánh ba trạng thái.
4. Chuẩn hóa logic dùng chung trong `src/pipelines/_common.py`, hợp đồng metadata và đường dẫn artifact giữa các module.
5. Tích hợp kết quả của các thành viên, xử lý lỗi merge ở ingestion/retrieval/observability và bổ sung regression test.
6. Xác minh pipeline end-to-end, chất lượng dữ liệu, metrics, idempotency và khả năng chạy offline với mock LLM.

Phần hỗ trợ ngoài phạm vi chính gồm sửa lỗi tích hợp trong `crossref.py`, `index.py` và `quality.py`. Các thay đổi này chỉ nhằm khôi phục hợp đồng chung của pipeline, không thay thế quyền sở hữu module của thành viên phụ trách.

## 3. Kết quả bàn giao

| Hạng mục | Kết quả | Artifact/module liên quan |
|---|---|---|
| Core configuration | Cấu hình có kiểu dữ liệu, kiểm tra giá trị, quản lý toàn bộ đường dẫn và tự tạo thư mục artifact | `src/core/config.py`, `src/core/utils.py`, `.env.example` |
| Baseline pipeline | Chạy hoàn chỉnh từ snapshot offline đến báo cáo đánh giá | `src/pipelines/phase1.py`, `data/results/baseline_metrics.json`, `data/reports/baseline_report.md` |
| Corruption/repair flow | Sinh trạng thái corrupted và repaired; đo được suy giảm và phục hồi | `src/pipelines/corruption_flow.py`, `data/results/corrupted_metrics.json`, `data/results/repaired_metrics.json` |
| Quality và freshness | Artifact tách riêng theo từng trạng thái, không còn ghi đè kết quả baseline | `data/quality/`, `src/observability/quality.py` |
| Retrieval index | Build/load nhất quán, manifest dùng đường dẫn portable và có validation | `src/retrieval/index.py` |
| Kiểm thử tích hợp | Toàn bộ test pass; có kiểm tra artifact, state transition và idempotency | `tests/test_core.py`, `tests/test_pipelines.py` |

## 4. Mô tả kỹ thuật

### 4.1. Cấu hình và hợp đồng dữ liệu

`Settings` là điểm vào duy nhất cho cấu hình pipeline. Các đường dẫn snapshot, dataset chuẩn hóa, index, quality result, evaluation result và report được suy ra từ một artifact root thay vì viết cứng trong từng module. Biến môi trường được parse và validate ngay khi khởi tạo; các thư mục cần thiết được tạo tập trung.

Đầu vào của pipeline gồm cấu hình, snapshot Crossref hoặc nguồn dữ liệu tương đương, test set và provider LLM. Đầu ra được phân tách theo trạng thái `baseline`, `corrupted`, `repaired`. Mỗi trạng thái có dataset, quality/freshness artifact, index, metrics và report tương ứng, giúp truy vết kết quả và tránh ghi đè chéo.

### 4.2. Luồng baseline

`phase1.py` điều phối theo thứ tự:

1. Nạp hoặc tạo dataset từ nguồn/snapshot.
2. Làm sạch và chuẩn hóa schema.
3. Chạy quality check và freshness check.
4. Chỉ xây dựng index khi quality gate của baseline đạt yêu cầu.
5. Chạy retrieval QA và evaluation.
6. Ghi metrics, report và metadata artifact.

Luồng này trả về kết quả có cấu trúc để script CLI, test và corruption flow có thể dùng chung thay vì suy luận trạng thái từ file rời rạc.

### 4.3. Luồng corruption và repair

`corruption_flow.py` tái sử dụng baseline, áp dụng tập corruption có seed/metadata, sau đó đánh giá trạng thái corrupted trước khi repair. Corrupted data vẫn được index và đánh giá dù quality gate thất bại, vì mục tiêu của thí nghiệm là đo tác động của lỗi dữ liệu. Sau repair, pipeline chạy lại quality gate; chỉ khi repaired data hợp lệ mới xây index và đánh giá phục hồi.

Luồng cũng kiểm tra các artifact bắt buộc và tránh phụ thuộc vào biến cục bộ hoặc helper không tồn tại. Khi chạy lại cùng đầu vào/cấu hình, hash của dataset repaired và metrics repaired không đổi, xác nhận tính idempotent trong phép kiểm tra thực tế.

### 4.4. Lệnh xác minh

```powershell
$env:LLM_PROVIDER = "mock"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe script\run_phase1.py
.\.venv\Scripts\python.exe script\run_corruption_flow.py
```

Đợt xác minh cuối được chạy trong workspace cách ly, sử dụng snapshot offline và mock provider để không phụ thuộc mạng/API key. Kết quả test: **19 passed**. `pip check` trả về **No broken requirements found**.

## 5. Quyết định kỹ thuật quan trọng

### Quyết định: quality gate theo trạng thái

Hai phương án đã được cân nhắc:

- Dừng pipeline ngay khi bất kỳ trạng thái nào fail quality gate.
- Áp dụng gate theo mục đích: baseline và repaired phải pass trước khi dùng tiếp; corrupted được phép tiếp tục để đo ảnh hưởng.

Tôi chọn phương án thứ hai. Nếu dừng corrupted flow ngay tại quality check, hệ thống chỉ chứng minh được rằng dữ liệu lỗi bị phát hiện, nhưng không thể định lượng lỗi đó làm retrieval và answer quality giảm bao nhiêu. Kết quả thực nghiệm `Pass → Fail → Pass` cùng các metric `1.0 → thấp hơn → 1.0` cho thấy quyết định này vừa giữ rào chắn cho dữ liệu dùng thật, vừa phục vụ đúng mục tiêu observability của bài lab.

## 6. Lỗi/blocker đã xử lý

Sau khi tích hợp thay đổi từ nhiều nhánh, pipeline gặp các lỗi sau:

- `src/ingestion/crossref.py` còn đoạn merge dư, gây `IndentationError`.
- `src/retrieval/index.py` có hai hướng triển khai build/load không đồng nhất.
- `corruption_flow.py` gọi helper/biến chưa định nghĩa, thiếu return và kiểm tra artifact.
- Freshness/quality artifact của corrupted có thể ghi đè kết quả baseline.

Nguyên nhân gốc là các implementation song song được merge nhưng hợp đồng đầu vào/đầu ra và phần residue chưa được kiểm tra end-to-end. Tôi loại bỏ đoạn mã dư, thống nhất `LocalEmbeddingIndex.build/load`, phục hồi hợp đồng của hai pipeline, tách đường dẫn quality/freshness theo trạng thái và bổ sung test hồi quy. Sau sửa, toàn bộ **19 test pass** và flow baseline/corrupted/repaired chạy hoàn chỉnh.

## 7. Trả lời câu hỏi end-to-end

### 7.1. Pipeline có chạy hoàn chỉnh không?

Có. Pipeline đã chạy từ snapshot offline qua cleaning, quality/freshness, indexing, retrieval QA, evaluation và reporting. Corruption flow tiếp tục tạo dữ liệu lỗi, đo suy giảm, repair và đo phục hồi.

### 7.2. Artifact có đầy đủ và truy vết được không?

Có. Artifact được tách theo trạng thái và đặt dưới `data/quality`, `data/results`, `data/reports` cùng các thư mục dataset/index tương ứng. Metadata trong report/metrics giúp xác định trạng thái và nguồn dữ liệu của lần chạy.

### 7.3. Quality gate có phản ứng đúng không?

Có. Baseline pass, corrupted fail và repaired pass. Corrupted vẫn được đánh giá có chủ đích để quan sát mức suy giảm; repaired chỉ đi tiếp sau khi vượt gate.

### 7.4. Repair có phục hồi chất lượng không?

Có. Retrieval hit rate, token F1, judge accuracy và mean judge score đều trở về mức baseline trong lần chạy xác minh.

### 7.5. Kết quả có tái lập được không?

Có trong cấu hình kiểm thử. Pipeline dùng snapshot offline, mock LLM và corruption có kiểm soát. Khi chạy lại, SHA-256 của repaired dataset và repaired metrics đều không đổi.

## 8. Phân tích metrics

| Chỉ số | Baseline | Corrupted | Repaired |
|---|---:|---:|---:|
| Retrieval hit rate | 1.0000 | 0.8000 | 1.0000 |
| Mean token F1 | 1.0000 | 0.8788 | 1.0000 |
| Judge accuracy | 1.0000 | 0.9000 | 1.0000 |
| Mean judge score | 5.0000 | 4.4000 | 5.0000 |
| Quality gate | Pass | Fail | Pass |
| Freshness | Fresh (1/24 stale) | Fresh (2/21 stale) | Fresh (1/24 stale) |

Corruption làm retrieval hit rate giảm 20 điểm phần trăm và mean token F1 giảm khoảng 0.1212. Judge accuracy giảm 10 điểm phần trăm; mean judge score giảm 0.6 điểm. Sau repair, cả bốn chỉ số trở về đúng mức baseline.

Các corruption được tiêm đồng thời (ví dụ làm trống summary, cắt title, loại record mới và thay đổi dữ liệu liên quan), nên kết quả hiện tại chỉ chứng minh ảnh hưởng tổng hợp. Không đủ bằng chứng để khẳng định riêng một corruption là nguyên nhân mạnh nhất nếu chưa chạy ablation theo từng kịch bản.

Điểm đáng chú ý là freshness vẫn `true` ở trạng thái corrupted vì tỷ lệ stale `2/21` vẫn dưới ngưỡng 25%, trong khi structural/data-quality checks đã fail. Điều này cho thấy freshness và data quality là hai tín hiệu bổ sung: freshness không thể thay thế kiểm tra schema, completeness và validity.

## 9. Bài học và hướng cải tiến

Ba bài học chính:

1. Hợp đồng artifact và state phải được định nghĩa trước khi tích hợp module; nếu không, code riêng lẻ có thể đúng nhưng pipeline vẫn lỗi.
2. Quality gate cần phản ánh mục đích từng trạng thái, không nên dùng một quy tắc dừng cứng cho cả production guard và experiment flow.
3. Test đơn vị cần đi kèm test tích hợp và một lần chạy end-to-end cách ly để phát hiện merge residue, đường dẫn ghi đè và phụ thuộc môi trường.

Nếu có thêm thời gian, tôi sẽ bổ sung corruption ablation để chạy từng lỗi độc lập, xuất contribution của từng scenario vào report; đồng thời đưa test, `pip check` và smoke run offline vào CI cho mỗi pull request.

## 10. Cam kết cá nhân

- [x] Tôi đã hoàn thành phần việc Pipeline Lead & Integrator được phân công.
- [x] Tôi đã kiểm tra các thay đổi của thành viên khác trước khi tích hợp.
- [x] Tôi đã chạy test và xác minh pipeline end-to-end.
- [x] Tôi đã ghi nhận trung thực kết quả, giới hạn và phần hỗ trợ ngoài phạm vi chính.
- [x] Tôi không đưa secret/API key vào repository.

**Người báo cáo:** Dương Dương

**MSSV:** 2A202602498

**Ngày:** 2026-09-25
