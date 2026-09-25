# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
| --- | --- |
| Khóa/Lớp | K4 |
| Tên nhóm | ThienLyOi |
| Repository | <https://github.com/Thees-Anh/K4A-Day10-ThienLyOi> |
| Ngày hoàn thành | 25/09/2026 |
| Phiên bản kết quả | `origin/main` — commit `d1bc79c` |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Dương Dương | 2A202602498 | Pipeline Lead & Integrator | Điều phối luồng, quản lý `core/`, kết nối `phase1.py` và `corruption_flow.py` |
| 2 | Nguyễn Phạm Oanh Oanh | 2A202602518 | Data Foundation Owner | Thu thập Crossref, làm sạch dữ liệu và khôi phục từ raw snapshot |
| 3 | Trần Thế Anh | 2A202602516 | RAG & Agent Specialist | MiniLM embedding, ChromaDB, truy vấn, QA và multi-provider Agent trong `retrieval/` |
| 4 | Đỗ Trịnh Huy Hoàng | 2A202602392 | Observability & Evaluation Lead | Great Expectations 1.x, Freshness SLA, test set, metrics và báo cáo đối chiếu |

## 2. Tóm tắt kết quả

Nhóm đã hoàn thiện pipeline hai pha cho dữ liệu bài báo Crossref, gồm thu thập có offline fallback, bảo toàn raw snapshot, làm sạch và chuẩn hóa schema, kiểm định chất lượng, tạo embedding MiniLM, lập chỉ mục ChromaDB, đánh giá RAG, tiêm lỗi có kiểm soát và phục hồi từ dữ liệu nguồn. Baseline xử lý 24 tài liệu, sinh dữ liệu sạch, bộ 10 câu hỏi, ba nhóm artifact về embedding, quality và evaluation, cùng báo cáo `phase1_report.md`. Trên baseline, Hit Rate, Token F1 và Judge Accuracy đều đạt 1.0; Mean Judge Score đạt 5/5. Sáu lỗi được tiêm gồm bỏ 5 tài liệu mới nhất, xóa summary, chèn noise, cắt title, làm cũ ngày và nhân đôi hai dòng. Tổng hợp các lỗi này làm Hit Rate giảm còn 0.8, Token F1 còn 0.8788 và quality gate chuyển từ Pass sang Fail; việc bỏ tài liệu mới tác động trực tiếp nhất đến retrieval. Repair tái tạo dữ liệu từ raw snapshot, đưa 24 dòng và toàn bộ metrics về mức baseline. Freshness vẫn Pass ở cả ba trạng thái, dù corrupted tăng tỷ lệ stale từ 4.17% lên 9.52%. Giới hạn chính là Ragas chưa được bật và kết quả hiện dựa trên tập nhỏ 24 tài liệu/10 câu hỏi.

## 3. Kiến trúc và luồng dữ liệu

```text
Crossref API hoặc offline snapshot
    -> raw response và parsed records
    -> cleaning, schema normalization, age_days
    -> Great Expectations quality gate + Freshness SLA
    -> MiniLM embedding + ChromaDB collection
    -> fixed test set + baseline evaluation
    -> six deterministic corruptions
    -> corrupted re-index + evaluation + quality check
    -> repair từ raw snapshot
    -> repaired re-index + comparison report
```

### Trách nhiệm của từng khối

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref API hoặc snapshot | Fetch với retry, fallback, parse DOI/metadata | `data/raw/crossref_response.json`, `crossref_records.json` | Thành viên 2 |
| Cleaning | Raw records | Chuẩn hóa text/date/list, khử trùng DOI, tính `age_days` | `data/clean/papers_clean.*` | Thành viên 2 |
| Embedding/index | Clean DataFrame | MiniLM 384 chiều, cosine index, metadata lookup | `data/embeddings/`, `data/chroma/` | Thành viên 3 |
| Evaluation | Chroma index + fixed test set | Hit Rate, Token F1, LLM judge | `data/eval/`, `data/results/*metrics.json` | Thành viên 4 |
| Observability | Clean/corrupted/repaired DataFrame | GX 1.x expectations và freshness SLA | `data/quality/` | Thành viên 4 |
| Corruption/repair | Clean data + raw snapshot | Tiêm 6 lỗi; tái tạo idempotent từ raw | `corruption_log.json`, repaired artifacts | Thành viên 2 và 1 |
| Orchestration | Settings và các module | Chạy đúng thứ tự, dừng trước index nếu baseline gate fail | `data/reports/*.md` | Thành viên 1 |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` | `openrouter` |
| `LLM_MODEL` | `openai/gpt-4o` |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày; tối đa 25% dòng stale |
| Random seed | Không dùng; corruption chọn dòng theo thứ tự xác định |

API key được cấu hình qua `.env`; file này nằm trong `.gitignore` và không được đưa vào báo cáo hoặc repository.

### Lệnh cài đặt và chạy

```bash
uv sync
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
```

### Kết quả tái hiện

| Lệnh | Trạng thái | Thời điểm chạy gần nhất | Bằng chứng |
| --- | --- | --- | --- |
| Baseline pipeline | Thành công | 25/09/2026 09:14 UTC | `data/reports/phase1_report.md`, `baseline_metrics.json` |
| Corruption flow | Thành công | 25/09/2026 09:18 UTC | `data/reports/corruption_report.md`, ba file metrics |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref Works API: `https://api.crossref.org/works`; lần chạy báo cáo dùng offline snapshot |
| Query/filter | `agentic retrieval augmented generation large language model`; `from-pub-date:2026-03-29,has-abstract:true` |
| Thời điểm chạy baseline | `2026-09-25T09:14:53.298399+00:00` |
| Số record nhận được | 24/24 |
| Retry/backoff | Tối đa 3 lần; retry HTTP 429/500/502/503/504; backoff 0.5 rồi 1 giây giữa các lần thử và hỗ trợ `Retry-After` tối đa 5 giây |

### Raw và clean schema

| Trường | Kiểu | Bắt buộc? | Ý nghĩa | Xử lý khi thiếu/sai |
| --- | --- | --- | --- | --- |
| `paper_id` | string/DOI | Có | Khóa tài liệu và ground-truth ID | Chuẩn hóa DOI; loại record thiếu; khử trùng giữ bản đầu |
| `title` | string | Có | Tiêu đề tài liệu | Bỏ markup/khoảng trắng; loại record thiếu |
| `summary` | string | Có theo quality gate | Nội dung phục vụ QA | Bỏ JATS/HTML; summary dưới 30 ký tự bị gate phát hiện |
| `authors`, `categories` | list[string] | Không | Tác giả và lĩnh vực | Chuẩn hóa, loại phần tử rỗng/trùng; tạo trường `*_joined` |
| `published`, `updated` | ISO date | `published` có | Ngày xuất bản/cập nhật | Parse nhiều định dạng; loại record không có ngày xuất bản hợp lệ |
| `age_days` | integer | Có | Tuổi dữ liệu tại thời điểm chạy | Tính `run_date - published`; giá trị thiếu/không hợp lệ làm freshness fail-closed |
| `text_for_embedding` | string | Có | Văn bản đầu vào MiniLM | Tạo lại sau mọi thay đổi dữ liệu |

### Quy tắc cleaning

| Quy tắc | Quality dimension | Số record bị tác động | Cách xác minh |
| --- | --- | ---: | --- |
| Chuẩn hóa DOI, text, JATS/HTML và khoảng trắng | Validity/Consistency | 24 được chuẩn hóa | `papers_clean.csv` |
| Loại record thiếu DOI, title hoặc published hợp lệ | Completeness | 0 trong snapshot hiện tại | Raw 24 → clean 24 |
| Khử trùng theo `paper_id` | Uniqueness | 0 trong baseline | GX uniqueness Pass |
| Tạo `summary_chars`, `age_days`, các trường joined | Completeness/Freshness | 24 | Clean schema và quality report |

`text_for_embedding` ghép năm dòng `Title`, `Authors`, `Published`, `Categories`, `Summary`. Document ID dùng DOI trong `paper_id`; Chroma record ID thêm chỉ số dòng để bảo đảm duy nhất. `age_days` là số ngày nguyên giữa thời điểm chạy và ngày xuất bản.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 10 |
| `question_type` | `summary`, `authors`, `date`, `categories` |
| Ground-truth document ID | DOI lấy từ `paper_id` của clean dataset |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection | ChromaDB cosine; `papers-baseline`, `papers-corrupted`, `papers-repaired` |
| Retrieval `top_k` | 4 |
| LLM provider/model | OpenRouter / `openai/gpt-4o` |
| Test set dùng chung | `data/eval/test_set.json` |

Test set được tạo từ baseline rồi giữ nguyên cho cả ba trạng thái. Nhờ vậy, thay đổi metrics phản ánh thay đổi của dữ liệu/index thay vì thay đổi độ khó hoặc ground truth của bộ câu hỏi.

## 7. Kết quả baseline

### Artifact checklist

| Artifact | Đường dẫn | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| Raw response/records | `data/raw/` | Có | 24 records |
| Cleaned dataset | `data/clean/papers_clean.csv/json` | Có | 24 dòng |
| Embedding manifest/index | `data/embeddings/`, `data/chroma/` | Có | Collection baseline |
| Evaluation set | `data/eval/test_set.json` | Có | 10 câu hỏi |
| Baseline metrics | `data/results/baseline_metrics.json` | Có | 10 samples |
| Quality/freshness | `data/quality/` | Có | Baseline Pass/Fresh |
| Baseline report | `data/reports/phase1_report.md` | Có | Đã sinh tự động |

### Baseline metrics

| Metric | Giá trị | Diễn giải |
| --- | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | Cả 10 câu đều tìm thấy ground-truth document trong top-k |
| `mean_token_f1` | 1.0000 | Câu trả lời khớp token với ground truth trên tập kiểm thử |
| `judge_accuracy` | 1.0000 | 100% câu được judge chấp nhận |
| `mean_judge_score` | 5.0000 | Điểm judge trung bình đạt mức tối đa 5/5 |
| Ragas | N/A | Chưa bật; cần `RUN_RAGAS=1` để chạy lượt đánh giá chậm |

## 8. Data quality và freshness

### Quality checks

| Check | Quality dimension | Ngưỡng/kỳ vọng | Baseline | Bằng chứng |
| --- | --- | --- | --- | --- |
| Row count | Completeness | 5–5000 | Pass: 24 | `baseline_quality_report.json` |
| Required values | Completeness | `paper_id`, `title`, `text_for_embedding` không null/blank | Pass: 0 lỗi | Cùng artifact |
| Unique paper ID | Uniqueness | 100% duy nhất | Pass: 24/24 | Cùng artifact |
| Summary length | Validity | Tối thiểu 30 ký tự | Pass: 24/24 | Cùng artifact |

### Freshness

| Thuộc tính | Giá trị |
| --- | --- |
| Freshness được đo tại | Clean baseline DataFrame, trước khi index |
| Ngày xuất bản mới nhất/cũ nhất | 2026-07-22 / 2026-03-28 |
| Ngưỡng freshness | `age_days > 180`; tỷ lệ stale không vượt 25% |
| Trạng thái baseline | Fresh |
| Lý do | 1/24 dòng stale, tương đương 4.17%, thấp hơn ngưỡng 25% |

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Record bị tác động | Quality signal/kết quả | Cách repair |
| --- | --- | ---: | --- | --- |
| `drop_latest_records` | Bỏ 20% dòng mới nhất | 5 | Corpus giảm 24 → 19 trước khi duplicate; Hit Rate tổng hợp giảm | Tái tạo từ raw snapshot |
| `blank_summary` | Xóa summary và đặt length = 0 | 1 | Required values và summary length Fail | Làm sạch lại từ raw |
| `inject_noise` | Thêm marker `invalid-token-9137` | 1 | Context bị nhiễu; được ghi trong log | Làm sạch lại từ raw |
| `truncate_title` | Cắt title còn tối đa 7 ký tự | 1 | Semantic signal của title suy giảm | Khôi phục title từ raw |
| `stale_date` | Lùi ngày 365 ngày | 1 | Stale rows tăng 1 → 2; freshness vẫn Pass | Tính lại ngày/age từ raw |
| `duplicate_rows` | Nhân đôi các dòng đầu | 2 | Uniqueness Fail; output cuối 21 dòng | Khử trùng khi cleaning lại |

Corruption log tồn tại tại `data/results/corruption_log.json`, chứa đủ sáu scenario, số dòng bị tác động, DOI và tham số liên quan. Repair không sửa trực tiếp dữ liệu corrupted mà đọc lại `crossref_records.json`, chạy lại cùng hàm cleaning và xây collection mới. Vì vậy kết quả được phục hồi từ nguồn lineage đáng tin cậy và có tính idempotent.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | 0.8000 | 1.0000 | -0.2000 | 100% phần bị mất | 2/10 câu mất ground-truth hit khi corpus bị lỗi |
| `mean_token_f1` | 1.0000 | 0.8788 | 1.0000 | -0.1212 | 100% phần bị mất | Nội dung lỗi làm giảm độ khớp câu trả lời |
| `judge_accuracy` | 1.0000 | 0.9000 | 1.0000 | -0.1000 | 100% phần bị mất | Một câu không đạt judge khi corrupted |
| `mean_judge_score` | 5.0000 | 4.4000 | 5.0000 | -0.6000 | 100% phần bị mất | Chất lượng câu trả lời suy giảm rồi hồi phục |
| Quality gate | Pass | Fail | Pass | Pass → Fail | Phục hồi hoàn toàn | Corrupted fail required values, uniqueness và summary length |
| Freshness | Pass (1/24) | Pass (2/21) | Pass (1/24) | Stale +5.36 điểm % | Về baseline | Corruption làm xấu freshness nhưng chưa vượt SLA 25% |

Kết luận nhân quả:

1. Bỏ 5 tài liệu mới nhất cùng các lỗi nội dung/duplicate làm quality gate Fail và giảm độ bao phủ corpus, kéo Hit Rate từ 1.0 xuống 0.8, Token F1 xuống 0.8788 và Judge Score xuống 4.4.
2. Repair từ raw snapshot khôi phục 24 dòng sạch, đưa required values/uniqueness/summary length về Pass và phục hồi toàn bộ bốn metrics về baseline.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Các branch thành viên có code/artifact mới nhưng branch làm việc của thành viên 3 vẫn nhìn thấy module `TODO` và thiếu metrics.
- **Nguyên nhân:** Branch local chưa cập nhật sau khi các PR được merge vào `main`; local `main` chậm hơn `origin/main` năm commit.
- **Cách xử lý:** Fetch remote, kiểm tra trực tiếp `origin/main`, dùng PR để hợp nhất module và giữ lịch sử đóng góp; trước lần chạy cuối cần cập nhật local `main` rồi đồng bộ branch cá nhân.
- **Cách xác minh:** `git log origin/main`, `git diff main..origin/main` và sự tồn tại của artifacts tại commit `d1bc79c`.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
| --- | --- | --- |
| Chỉ 24 tài liệu và 10 câu hỏi | Metrics 1.0 có thể chưa đại diện cho tải thực tế | Tăng corpus/test set, phân tầng theo loại câu hỏi và báo confidence interval |
| Ragas chưa chạy | Thiếu context precision/recall và faithfulness | Bật `RUN_RAGAS=1`, lưu kết quả và so sánh ba trạng thái |
| Corruption có tính xác định và quy mô nhỏ | Chưa khảo sát độ nhạy theo mức lỗi | Chạy nhiều mức corruption và nhiều seed, vẽ đường cong suy giảm/phục hồi |
| Freshness corrupted vẫn Pass | Một lỗi stale chưa đủ kích hoạt SLA | Thêm test riêng làm stale ratio vượt 25% và xác nhận gate Fail |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact tồn tại trên `origin/main`.
- [x] `.env` nằm trong `.gitignore`; báo cáo không chứa API key/token.
- [ ] Cập nhật local `main`, chạy lại hai pipeline trên đúng commit dùng để nộp và xác nhận exit code 0.
- [ ] Hoàn thành/đổi tên báo cáo cá nhân riêng cho đủ bốn thành viên.
- [ ] Kiểm tra đủ bốn thành viên tại GitHub **Insights → Contributors** trên `main`.
- [ ] Mỗi thành viên tự nộp link repository lên VLearn LMS.
