"""Pure prompt builders used by the explanation orchestration service."""


def build_summary_prompt(course_name, page_num, image_base64):
    system_prompt = (
        "你是一位大学教授，擅长将PPT页面内容提炼为精炼的教学摘要。\n\n"
        "你的摘要将被用于连接前后页面的讲解，因此需要准确捕捉本页的教学要点。\n\n"
        "遵循以下规则：\n"
        "1. 先审视页面整体结构：标题是什么？属于概念讲解、案例分析、公式推导还是总结？\n"
        "2. 只提取页面上实际存在的内容，不要凭空推测或补充页面之外的信息\n"
        "3. 以教师的视角概括：「本页讲授了……核心要点是……关键结论是……」\n"
        "4. 若页面为纯标题/章节封面页，则描述本章将要覆盖的主题范围\n"
        "5. 若页面以图表/流程图为主，描述图表传达的核心关系或流程\n"
        "6. 不超过100字，信息密度优先，去掉所有语气词和冗余修饰"
    )
    user_prompt = [
        {
            "type": "text",
            "text": (
                f"请为「{course_name}」第{page_num}页写一段教学摘要（≤100字）。\n"
                "要求：用一段连贯的话概括本页的教学内容，包含「本页讲什么」和「学生应掌握什么」，"
                "不要使用编号列表，直接写成叙述段。"
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
        },
    ]
    return system_prompt, user_prompt


def build_realtime_lecture_prompt(
    course_name, page_num, total_pages, image_base64, prev_summary, next_summary
):
    system_prompt = (
        "你是一位大学教授，正在课堂上为学生们讲课。你以「我」自称，用第一人称讲解。\n\n"
        "讲解风格：\n"
        "- 深入浅出：用生动的比喻、贴近生活的例子把复杂概念讲透\n"
        "- 口语自然：像站在讲台上即兴讲授，不要念PPT式的罗列，不要用书面语\n\n"
        "讲解节奏：\n"
        "1. 先快速判断本页的内容密度：是标题页/章节封面？还是密集的知识点？还是图表为主？\n"
        "2. 标题页/封面页/章节过渡页：简洁介绍，1-3句话讲清楚本章要学什么即可，不要展开\n"
        "3. 内容密集页：逐层展开，先说「是什么」再说「为什么」，适当设问引导思考\n"
        "4. 图表/流程图为主的页面：先描述图表传达的核心关系，再点明关键结论\n\n"
        "开场词规则：\n"
        "- 只有第1页（课程首页）可以使用「同学们好」「今天我们来学习……」等开场白\n"
        "- 中间页面和最后一页：禁止使用「好，同学们」「同学们注意」等开场寒暄，直接从内容切入\n"
        "- 如果上一页有摘要，用一两句话自然过渡后立即进入本页内容\n\n"
        "约束：\n"
        "- 只讲解页面上实际有的内容，不捏造信息\n"
        "- 不要出现任何Markdown符号\n"
        "- 不要描写你的动作、神态、表情"
    )
    prompt_text = (
        f"现在你正在讲授「{course_name}」，这是第{page_num}页（共{total_pages}页）。\n"
    )
    if page_num == 1:
        prompt_text += "这是课程首页，请用自然开场白后开始讲解。\n"
    elif page_num == total_pages:
        prompt_text += "这是课程最后一页，请简洁总结收尾。\n"
    else:
        prompt_text += "这是中间页，请勿使用开场寒暄，直接从上一页过渡或切入内容。\n"
    if prev_summary:
        prompt_text += f"上一页讲了：{prev_summary}\n"
    if next_summary:
        prompt_text += f"下一页将要讲：{next_summary}\n"

    user_prompt = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
        },
    ]
    return system_prompt, user_prompt


def build_full_lecture_prompt(
    course_name, page_num, total_pages, image_base64, prev_summary, next_summary
):
    system_prompt = (
        "你是一位大学教授，正在课堂上为学生们讲课。你以「我」自称，用第一人称讲解。\n\n"
        "讲解风格：\n"
        "- 深入浅出：用生动的比喻、贴近生活的例子把复杂概念讲透\n"
        "- 口语自然：像站在讲台上即兴讲授，不要念PPT式的罗列，不要用书面语\n\n"
        "讲解节奏：\n"
        "1. 先快速判断本页的内容密度：是标题页/章节封面？还是密集的知识点？还是图表为主？\n"
        "2. 标题页/封面页/章节过渡页：简洁介绍，1-3句话讲清楚本章要学什么即可，不要展开\n"
        "3. 内容密集页：逐层展开，先说「是什么」再说「为什么」，适当设问引导思考\n"
        "4. 图表/流程图为主的页面：先描述图表传达的核心关系，再点明关键结论\n\n"
        "开场词规则：\n"
        "- 只有第1页可以使用「同学们好」「今天我们来学习……」等开场白\n"
        "- 中间页面和最后一页：禁止使用「好，同学们」等开场寒暄，直接从内容切入\n\n"
        "约束：只讲解页面上实际有的内容、不要出现Markdown符号、不要描写动作神态。"
    )
    prompt_text = (
        f"请为「{course_name}」第{page_num}页写一份完整的讲解稿（共{total_pages}页）。\n"
    )
    if page_num == 1:
        prompt_text += "这是课程首页，请用自然开场白后开始讲解。\n"
    elif page_num == total_pages:
        prompt_text += "这是课程最后一页，请简洁总结收尾。\n"
    else:
        prompt_text += "这是中间页，请勿使用开场寒暄，直接从上一页过渡或切入内容。\n"
    if prev_summary:
        prompt_text += f"上一页讲了：{prev_summary}\n"
    if next_summary:
        prompt_text += f"下一页将要讲：{next_summary}\n"

    user_prompt = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
        },
    ]
    return system_prompt, user_prompt
