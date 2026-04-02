import os
import json
import base64
import PyPDF2
import pdfplumber
import requests
import time
import concurrent.futures


class PDFVox:
    def __init__(self, api_key):
        """Initialize PDF explainer"""
        self.api_key = api_key

    def _stream_chat_response(self, system_prompt, user_prompt, image_base64=None, max_tokens=800):
        """Send a streaming chat request and collect the result as text."""
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        content_items = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if image_base64:
            content_items.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }
            )

        data = {
            "model": "Qwen/Qwen3-VL-32B-Thinking",
            "messages": content_items,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": True,
        }

        explanation = ""
        with requests.post(url, headers=headers, json=data, stream=True, timeout=180) as response:
            response.raise_for_status()
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(chunk_size=4096, decode_unicode=False):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        explanation += delta
                except json.JSONDecodeError:
                    continue
        return explanation.replace("\u0000", "")

    def analysis(self, pdf_path):
        """Parse PDF file and extract page images"""
        content = []

        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            page_num = len(reader.pages)
            print(f"Total PDF pages: {page_num}")

            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    image = page.to_image(resolution=300)
                    import io

                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format="PNG")
                    img_bytes.seek(0)

                    img_base64 = base64.b64encode(img_bytes.getvalue()).decode("utf-8")

                    content.append({"page": i + 1, "image": img_base64})
                    print(f"Processed page {i + 1}")
        return content

    def understand(self, content):
        """Understand content and generate explanations for each page with smooth transitions using controlled concurrency"""

        explanations = []
        total_pages = len(content)

        def process_page(item):
            page = item["page"]
            image_base64 = item["image"]
            max_retries = 3
            retry_delay = 2  # seconds

            for attempt in range(max_retries):
                try:
                    system_prompt = (
                        "你是一位大学教授，正在给学生讲解课程。请以专业、清晰、有条理的方式讲解PDF内容，语气像在课堂上讲课一样。"
                        "重点讲解核心概念、理论框架和关键知识点，避免冗余内容和对无关元素的过多讲解。"
                        "讲解要逻辑连贯，层次分明，适合大学学生的理解水平。"
                        "请在结尾给出自然过渡句，连接前后章节内容，并在最后补充一段简短衔接段落（不超过两句话）。"
                    )
                    user_prompt = [
                        {
                            "type": "text",
                            "text": f"请为以下机器学习课程导论PDF的第{page}页内容生成一段课堂讲解，要求：\n"
                                    "1. 以大学教授的语气和风格讲解\n"
                                    "2. 重点讲解核心概念、理论框架和关键知识点\n"
                                    "3. 避免冗余内容和对无关元素的过多讲解\n"
                                    "4. 讲解逻辑清晰，层次分明，适合大学学生理解\n"
                                    "5. 讲解时长自由发挥，可长可短。\n"
                                    "6. 不要带有老师的神态描写与动作描写，不要带有类似于markdown加粗等符号，单纯生成讲解稿。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        },
                    ]

                    explanation = self._stream_chat_response(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        image_base64=None,
                        max_tokens=800,
                    )

                    if not explanation:
                        raise ValueError("未从流式接口获取到讲解内容")

                    print(f"Generated explanation for page {page}")
                    return {"page": page, "explanation": explanation}

                except Exception as e:
                    if attempt < max_retries - 1:
                        print(
                            f"Error generating explanation for page {page} (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        print(
                            f"Error generating explanation for page {page} (all attempts failed): {e}"
                        )
                        return {
                            "page": page,
                            "explanation": f"Sorry, unable to generate explanation for page {page}.",
                        }

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(2, total_pages)
        ) as executor:
            future_to_page = {
                executor.submit(process_page, item): item for item in content
            }

            for future in concurrent.futures.as_completed(future_to_page):
                result = future.result()
                explanations.append(result)

        explanations.sort(key=lambda x: x["page"])

        for idx, item in enumerate(explanations):
            prev_exp = explanations[idx - 1]["explanation"] if idx > 0 else ""
            next_exp = explanations[idx + 1]["explanation"] if idx < total_pages - 1 else ""
            transition = self.generate_transition_paragraph(
                page=item["page"],
                prev_exp=prev_exp,
                curr_exp=item["explanation"],
                next_exp=next_exp,
            )
            item["transition"] = transition

        return explanations

    def generate_transition_paragraph(self, page, prev_exp, curr_exp, next_exp):
        """Generate a short connecting paragraph for current page based on previous and next pages."""
        if not curr_exp:
            return ""

        system_prompt = (
            "你是一位大学教授，擅长将课程内容帮助学生在章节之间自然衔接。"
            "请根据当前页面讲解内容生成一段简短衔接段落（1-2句话），连接前后页内容，帮助听众过渡到下一主题。"
            "如果没有前页或后页，可仅围绕当前页内容进行简要过渡。"
        )

        user_prompt = (
            f"第{page}页当前讲解：{curr_exp}\n"
            f"上一页讲解：{prev_exp}\n"
            f"下一页讲解：{next_exp}\n"
            "请基于上述内容生成一个清晰、自然的过渡段落，不要带列表格式或额外标记。"
        )

        try:
            transition = self._stream_chat_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_base64=None,
                max_tokens=120,
            )
            transition = transition.strip()
            if not transition:
                transition = ""
            return transition
        except Exception as e:
            print(f"Failed to generate transition paragraph for page {page}: {e}")
            return ""

    def save_explanations_to_txt(self, explanations, output_dir, file_name="explanations.txt"):
        """Save page explanations and transition paragraphs to one text file."""
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, file_name)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("PDF 讲解稿（含衔接段落）\n")
            f.write("========================================\n\n")
            for item in explanations:
                page = item.get("page")
                explanation = item.get("explanation", "")
                transition = item.get("transition", "")

                f.write(f"--- 第{page}页讲解 ---\n")
                f.write(explanation.strip() + "\n\n")
                if transition.strip():
                    f.write(f"--- 第{page}页衔接段落 ---\n")
                    f.write(transition.strip() + "\n\n")
                f.write("----------------------------------------\n\n")

        print(f"Saved full explanation manuscript to: {output_path}")
        return output_path

    def TTS(self, content, output_dir):
        """Convert content to speech using SiliconFlow FunAudioLLM/CosyVoice2-0.5B with multithreading and retry mechanism"""
        os.makedirs(output_dir, exist_ok=True)

        audio_files = []

        def process_audio(item):
            page = item["page"]
            explanation = item.get("explanation", "")
            transition = item.get("transition", "")
            max_retries = 3
            retry_delay = 3  # seconds

            full_text = explanation.strip()
            if transition.strip():
                full_text = f"{full_text}\n\n{transition.strip()}"

            for attempt in range(max_retries):
                try:
                    url = "https://api.siliconflow.cn/v1/audio/speech"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    }
                    data = {
                        "model": "fnlp/MOSS-TTSD-v0.5",
                        "voice": "fnlp/MOSS-TTSD-v0.5:alex",
                        "input": full_text,
                        "response_format": "mp3",
                    }

                    if not full_text:
                        raise ValueError("空讲解内容，无法合成语音")

                    with requests.post(
                        url,
                        headers=headers,
                        json=data,
                        stream=True,
                        timeout=180,
                    ) as response:
                        if response.status_code != 200:
                            print(
                                f"TTS API failed status {response.status_code}, body: {response.text}"
                            )
                        response.raise_for_status()

                        audio_path = os.path.join(output_dir, f"page_{page}.mp3")
                        content_type = response.headers.get("Content-Type", "")
                        bytes_received = 0

                        if "application/json" in content_type.lower():
                            body = response.json()
                            audio_base64 = (
                                body.get("audio_base64")
                                or body.get("data")
                                or body.get("result")
                            )
                            if not audio_base64:
                                raise ValueError("TTS返回JSON中未找到音频字段")

                            if isinstance(audio_base64, dict) and "base64" in audio_base64:
                                audio_base64 = audio_base64.get("base64")

                            if isinstance(audio_base64, str) and audio_base64.startswith("data:"):
                                audio_base64 = audio_base64.split(",", 1)[1]

                            audio_bytes = base64.b64decode(audio_base64)
                            with open(audio_path, "wb") as f:
                                f.write(audio_bytes)
                            bytes_received = len(audio_bytes)
                            print(f"[Page {page}] 已写入 {bytes_received} 字节（JSON格式音频）", flush=True)
                        else:
                            with open(audio_path, "wb") as f:
                                print(f"[Page {page}] 开始接收流式语音数据...")
                                for chunk in response.iter_content(chunk_size=4096):
                                    if chunk:
                                        f.write(chunk)
                                        bytes_received += len(chunk)
                                        if bytes_received % (1024 * 50) < 4096:
                                            print(f"[Page {page}] 已接收 {bytes_received} 字节", flush=True)

                        if bytes_received == 0:
                            raise ValueError("TTS流无内容")

                    print(f"Generated audio for page {page}")
                    return {"page": page, "audio_path": audio_path}

                except Exception as e:
                    if attempt < max_retries - 1:
                        print(
                            f"Error synthesizing speech for page {page} (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        print(
                            f"Error synthesizing speech for page {page} (all attempts failed): {e}"
                        )
                        return {"page": page, "audio_path": None}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(3, len(content))
        ) as executor:
            future_to_page = {
                executor.submit(process_audio, item): item for item in content
            }

            for future in concurrent.futures.as_completed(future_to_page):
                result = future.result()
                if result["audio_path"]:
                    audio_files.append(result)

        audio_files.sort(key=lambda x: x["page"])
        return audio_files

    def process(self, pdf_path, output_dir):
        """Process PDF file completely"""
        print("Starting PDF processing...")

        content = self.analysis(pdf_path)
        explanations = self.understand(content)

        # Save combined explanation + transition manuscript to a single TXT file
        self.save_explanations_to_txt(explanations, output_dir)

        audio_files = self.TTS(explanations, output_dir)

        print("PDF processing completed!")
        return audio_files
