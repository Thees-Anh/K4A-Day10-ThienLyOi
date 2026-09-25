# Báo cáo vai trò cá nhân — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Trần Thế Anh |
| MSSV | 2A202602516 |
| Khóa/Lớp | K4 |
| Tên nhóm | ThienLyOi |
| Vai trò chính | RAG & Agent Specialist |
| Repository | <https://github.com/Thees-Anh/K4A-Day10-ThienLyOi> |
| Branch | `RAG-&-Agent-Specialist/TheAnh` |
| Commit cá nhân | `4ee3aba` — `feat(retrieval): complete member 3 RAG and agent components` |
| Ngày hoàn thành | 25/09/2026 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| MiniLM embedding | `src/retrieval/embeddings.py`, `MiniLMEmbeddings` | Tên model, danh sách document hoặc query | Vector float đã chuẩn hóa cosine | Hoàn thành |
| ChromaDB vector index | `src/retrieval/index.py`, `LocalEmbeddingIndex` | Clean DataFrame và `Settings` | Ba collection, embedding manifest và kết quả search/lookup | Hoàn thành |
| Retrieval QA | `src/retrieval/qa.py` | Câu hỏi và top-k search results | `AnswerResult` cùng document IDs/context/title | Đã kiểm chứng tích hợp |
| Multi-provider Agent | `src/retrieval/agent.py`, `llm.py` | Settings, Chroma index và câu hỏi | Agent có semantic search và exact lookup tools | Đã kiểm chứng cấu hình OpenRouter |
| Retrieval tests | `tests/retrieval/test_index.py`, `test_qa.py` | DataFrame giả lập và fake embeddings | 7 test cho schema, index, search, load và QA | Hoàn thành |

Phần retrieval phụ thuộc vào clean schema của thành viên 2, đặc biệt các cột `paper_id`, `title`, `summary`, `published`, `authors_joined`, `categories_joined` và `text_for_embedding`. Output được thành viên 1 và 4 sử dụng để chạy pipeline và tính các metrics retrieval/answer.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Xác minh data contract | Cleaning và pipeline integration | Index báo rõ cột thiếu/null/rỗng thay vì lỗi Chroma khó hiểu |
| Kiểm tra artifact và metrics phục vụ báo cáo | Nhóm | Đối chiếu kết quả từ `origin/main` với JSON/report trước khi viết kết luận |
| Hoàn thiện báo cáo chung | Nhóm | `report/group_report.md` không còn placeholder và khớp artifacts |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Thêm validation cho embedding | `MiniLMEmbeddings` | Từ chối model/query rỗng; danh sách document rỗng trả `[]` | `pytest tests/retrieval` |
| Bảo vệ data contract trước khi index | `_build_documents()` | Phát hiện thiếu cột, DataFrame rỗng, ID/title/content null hoặc rỗng | Các test `test_build_documents_*` |
| Chuẩn hóa Chroma metadata | `_build_documents()` | Metadata luôn ở dạng chuỗi; URL tùy chọn không làm pipeline lỗi | Test metadata normalization |
| Làm index portable | `build()`, `load()` | Manifest ưu tiên đường dẫn tương đối, dùng được sau clone/pull | `test_build_search_and_portable_load` |
| Làm search an toàn với corpus nhỏ | `search()` | Kiểm tra query/top-k và giới hạn `n_results` theo collection count | Test top-k 10 trên collection 2 dòng |
| Kiểm chứng MiniLM thật | `all-MiniLM-L6-v2` | Sinh 2 vector 384 chiều, L2-normalized | Smoke test MiniLM |

Output cụ thể của phần việc là lớp `LocalEmbeddingIndex` có thể build/load ChromaDB, lookup chính xác bằng DOI/title và semantic search theo cosine. Khi tích hợp trên `main`, phần này tạo các manifest trong `data/embeddings/` và ba collection `papers-baseline`, `papers-corrupted`, `papers-repaired`. Metrics chung cho thấy retrieval Hit Rate lần lượt là 1.0, 0.8 và 1.0.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần RAG phải chuyển clean DataFrame thành vector index có thể tái sử dụng cho ba trạng thái dữ liệu. Nếu schema sai, metadata chứa kiểu không hợp lệ, `top_k` lớn hơn corpus hoặc manifest lưu đường dẫn tuyệt đối của máy tạo index, ChromaDB có thể lỗi khi build/search hoặc không load được trên máy thành viên khác. Đồng thời truy vấn phải trả lại đủ DOI, title, context và metadata để QA/evaluation đối chiếu ground truth.

### Cách triển khai

`MiniLMEmbeddings` bọc Sentence Transformers và bật `normalize_embeddings=True`, phù hợp với cosine distance. `LocalEmbeddingIndex` kiểm tra schema trước khi tạo documents, chuẩn hóa metadata thành chuỗi rồi build Chroma collection với không gian cosine. Collection được chọn theo manifest để cô lập baseline/corrupted/repaired. Khi search, query được embed cùng model; số kết quả được giới hạn bởi kích thước collection và distance được đổi thành similarity score `max(0, 1-distance)`. Manifest lưu documents, model, collection name và đường dẫn portable để index có thể được load lại.

QA ưu tiên exact title lookup nếu câu hỏi chứa tiêu đề trong dấu nháy, sau đó kết hợp semantic retrieval và loại trùng DOI. Agent cung cấp hai tools: semantic search và exact paper lookup; LLM được chọn qua provider cấu hình, không hard-code API key.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Pandas DataFrame có `paper_id`, `title`, `summary`, `published`, `authors_joined`, `categories_joined`, `text_for_embedding`; cùng `Settings` |
| Output | Chroma collection, JSON manifest, `list[SearchResult]` hoặc `AnswerResult` |
| Module phụ thuộc | `core.config`, `core.utils`, `ingestion.cleaning`, Sentence Transformers, ChromaDB |
| Module sử dụng output | `pipelines.phase1`, `pipelines.corruption_flow`, `evaluation.metrics`, `retrieval.qa`, `retrieval.agent` |
| Điều kiện lỗi | Thiếu/rỗng/null cột bắt buộc; query rỗng; `top_k <= 0`; collection rỗng; manifest/collection không tồn tại |

### Cách xác minh

```bash
uv run python -m pytest tests/retrieval -q
uv run python -c "from retrieval.embeddings import MiniLMEmbeddings; m=MiniLMEmbeddings('sentence-transformers/all-MiniLM-L6-v2'); v=m.embed_query('RAG'); print(len(v), abs(sum(x*x for x in v)-1.0) < 1e-4)"
```

- **Kết quả mong đợi:** Toàn bộ test pass; MiniLM trả vector 384 chiều và được chuẩn hóa.
- **Kết quả thực tế:** `7 passed`; smoke test in `384 True`.
- **Artifact/log:** Commit `4ee3aba`; `tests/retrieval/`; không chứa secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Manifest ban đầu lưu `persist_path` tuyệt đối, nên sau khi clone sang máy khác có thể trỏ tới thư mục của người tạo index.
- **Các phương án đã cân nhắc:** (1) luôn lưu absolute path; (2) bỏ path và luôn dùng config; (3) lưu relative path khi Chroma nằm trong project, nhưng vẫn hỗ trợ absolute path tùy chỉnh.
- **Phương án đã chọn:** Phương án 3; `build()` ưu tiên đường dẫn tương đối với project và `load()` resolve lại theo project hiện tại.
- **Lý do:** Giữ tính portable/reproducible mà không làm mất khả năng cấu hình storage ngoài project.
- **Bằng chứng:** Test build/load bằng `tmp_path` pass; loaded index trỏ đúng `settings.paths.chroma_dir` và search trả đúng DOI.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** `No Python at 'C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe'` khi gọi trực tiếp `.venv\Scripts\python.exe`.
- **Bước tái hiện:** Chạy `.\.venv\Scripts\python.exe --version` hoặc pytest bằng executable này.
- **Nguyên nhân gốc:** `.venv/pyvenv.cfg` trỏ đến Python 3.11 cũ không còn tồn tại; virtual environment không portable giữa các máy/đường dẫn cài Python.
- **Cách xử lý:** Dùng `uv sync --extra dev` để đồng bộ dependency và chạy lệnh qua `uv run`, công cụ tự chọn Python 3.11.9 hợp lệ.
- **Cách xác minh:** `uv run python --version` trả `Python 3.11.9`; `uv run python -m pytest tests/retrieval -q` trả `7 passed`.
- **Điều học được:** Không commit hoặc phụ thuộc vào virtual environment cục bộ; môi trường phải được tái tạo từ `pyproject.toml`/`uv.lock`.

## 7. Hiểu biết về luồng end-to-end

1. Crossref API hoặc snapshot cung cấp raw response. Ingestion parse thành `PaperRecord`; cleaning chuẩn hóa DOI, text, date, tạo `age_days` và `text_for_embedding`. Quality gate phải Pass trước khi MiniLM sinh embedding và ChromaDB lưu vector cùng metadata.
2. Evaluation set gồm 10 câu thuộc bốn loại và giữ DOI trong `ground_truth_doc_ids`. Retrieval Hit Rate kiểm tra DOI đúng có nằm trong top-k; QA answer được so với ground truth bằng Token F1 và judge metrics.
3. Quality checks đo cấu trúc/nội dung như row count, required values, uniqueness và summary length. Freshness đo tuổi dữ liệu và tỷ lệ record vượt 180 ngày; corrupted có thể fail quality nhưng vẫn pass freshness nếu tỷ lệ stale chưa vượt 25%.
4. Dùng cùng test set giúp phép so sánh ba trạng thái chỉ phản ánh thay đổi của corpus/index, không bị nhiễu bởi câu hỏi hoặc ground truth khác nhau.
5. Repair thành công khi dữ liệu được tái tạo từ raw snapshot, quality trở lại Pass, số dòng và freshness trở về baseline, đồng thời các metrics repaired phục hồi về mức baseline.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | 0.8000 | 1.0000 | Corruption làm mất hit ở 2/10 câu; repair phục hồi hoàn toàn |
| `mean_token_f1` | 1.0000 | 0.8788 | 1.0000 | Context thiếu/nhiễu làm câu trả lời kém khớp |
| `judge_accuracy` | 1.0000 | 0.9000 | 1.0000 | Một câu corrupted không đạt judge |
| `mean_judge_score` | 5.0000 | 4.4000 | 5.0000 | Chất lượng giảm 0.6 điểm rồi trở về 5/5 |
| Quality checks | Pass | Fail | Pass | Corrupted fail required values, uniqueness và summary length |
| Freshness status | Pass (1/24) | Pass (2/21) | Pass (1/24) | Tỷ lệ stale tăng nhưng vẫn dưới SLA 25% |

### Kết luận từ số liệu

1. Bỏ 5 tài liệu mới nhất, làm hỏng nội dung và tạo duplicate → quality gate chuyển Pass thành Fail, stale ratio tăng từ 4.17% lên 9.52% → Hit Rate giảm 0.2, Token F1 giảm 0.1212 và Judge Score giảm 0.6.
2. Tái tạo clean data và index mới từ raw snapshot → quality trở lại Pass, corpus trở lại 24 dòng và freshness về 1/24 stale → toàn bộ bốn metrics trở lại baseline.

Corruption ảnh hưởng rõ nhất tới RAG là `drop_latest_records`, vì nó xóa trực tiếp năm document khỏi corpus; nếu DOI ground truth không còn trong collection thì embedding tốt đến đâu cũng không thể retrieve tài liệu đó. Blank summary và truncate title tiếp tục làm giảm semantic signal, còn duplicate chủ yếu bị quality gate phát hiện.

Kết quả khác kỳ vọng là corruption `stale_date` không làm freshness Fail. Artifact cho thấy corrupted có 2/21 dòng stale, tương đương 9.52%, vẫn thấp hơn ngưỡng 25%; do đó kết luận đúng là freshness xấu đi nhưng vẫn Pass, không phải monitoring bị lỗi.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Data contract phải được kiểm tra ngay tại biên module; lỗi thiếu cột/null nên được báo trước khi gọi model hoặc ChromaDB.
2. Data quality và freshness là hai tín hiệu độc lập: một dataset có thể fail completeness/uniqueness nhưng vẫn nằm trong Freshness SLA.
3. Chất lượng RAG phụ thuộc trực tiếp vào độ bao phủ và nội dung corpus; model embedding không thể bù cho tài liệu bị mất hoặc metadata bị phá hỏng.

### Nếu có thêm thời gian

Tôi sẽ mở rộng retrieval tests thành benchmark nhiều query và nhiều mức corruption, đo Recall@k/MRR bên cạnh Hit Rate, chạy Ragas với `RUN_RAGAS=1`, đồng thời thêm CI để chạy unit tests trên mọi Pull Request. Cải thiện được xác minh bằng coverage, tỷ lệ test pass và đường cong metric theo mức corruption.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trần Thế Anh

**Ngày xác nhận:** 2026-09-25
