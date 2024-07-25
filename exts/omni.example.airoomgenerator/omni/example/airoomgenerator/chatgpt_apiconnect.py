# SPDX-FileCopyrightText: Copyright (c) 2023 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import carb
import re
import asyncio
import yaml
import os
from .prompts import system_input, user_input_template, example_user_input, example_assistant_input
from .deep_search import query_items
from .item_generator import place_greyboxes, place_deepsearch_results
import openai

async def chatGPT_call(user_prompt: str):
    # Load your API key from an environment variable or secret management service
    settings = carb.settings.get_settings()
    
    model_name = settings.get_as_string("/persistent/exts/omni.example.airoomgenerator/model_name")
    openai_config_path = settings.get_as_string("/persistent/exts/omni.example.airoomgenerator/openai_config_path")
    
    # Send a request API
    try:
        llm_config_path = os.path.expanduser(openai_config_path)
        assert os.path.exists(llm_config_path), f"Model config file not found at {llm_config_path}"
        with open(llm_config_path, 'r') as f:
            llm_config_dict = yaml.safe_load(f)
        llm_config = llm_config_dict['llms'][model_name]

        messages = [
            {"role": "system", "content": system_input},
            {"role": "user", "content": example_user_input},
            {"role": "assistant", "content": example_assistant_input},
            {"role": "user", "content": user_prompt}
        ]

        # Create a completion using the chatGPT model
        openai_client = openai.AsyncOpenAI(api_key=llm_config['api_key'],
                                          base_url=llm_config['base_url'],
                                          timeout=llm_config['timeout']
                                          )
        response = await openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=llm_config['timeout']
        )
        text = response.choices[0].message.content
    except Exception as e:
        carb.log_error("An error as occurred")
        return None, str(e)

    # Parse data that was given from API
    try:
        # Regex patterns to extract python code enclosed in GPT response
        patterns = [
            r'```json(.*?)```',
            r'```(.*?)```'
        ]
        code_string = None
        for pattern in patterns:
            code_string = re.search(pattern, text, re.DOTALL)
            if code_string is not None:
                code_string = code_string.group(1).strip()
                break
        code_string = text if not code_string else code_string

        #convert string to  object
        data = json.loads(code_string)
    except ValueError as e:
        carb.log_error(f"Exception occurred: {e}")
        return None, text
    else: 
        # Get area_objects_list
        object_list = data['area_objects_list']
        
        return object_list, text

async def call_Generate(prim_info, prompt, use_chatgpt, use_deepsearch, response_label, progress_widget):
    run_loop = asyncio.get_event_loop()
    progress_widget.show_bar(True)
    task = run_loop.create_task(progress_widget.play_anim_forever())
    response = ""
    #chain the prompt
    area_name = prim_info.area_name.split("/World/Layout/")
    user_prompt = user_input_template.format(
        area_name=area_name[-1].replace("_", " "),
        area_size=f'{round(float(prim_info.length) * 100)}x{round(float(prim_info.width) * 100)}',
        area_origin_at='(0,0,0)',
        user_prompt=prompt,
    )
    root_prim_path = "/World/Layout/GPT/"
    if prim_info.area_name != "":
        root_prim_path = prim_info.area_name + "/items/"
    
    if use_chatgpt:          #when calling the API
        objects, response = await chatGPT_call(user_prompt)
    else:                       #when testing and you want to skip the API call
        data = json.loads(example_assistant_input)
        objects = data['area_objects_list']
    if objects is None:
        response_label.text = response
        return 

    if use_deepsearch:
        settings = carb.settings.get_settings()
        nucleus_path = settings.get_as_string("/persistent/exts/omni.example.airoomgenerator/deepsearch_nucleus_path")
        filter_path = settings.get_as_string("/persistent/exts/omni.example.airoomgenerator/filter_path")
        filter_paths = filter_path.split(',')
        
        queries = list()                        
        for item in objects:
            queries.append(item['object_name'])

        query_result = await query_items(queries=queries, url=nucleus_path, paths=filter_paths)
        if query_result is not None:
            place_deepsearch_results(
                gpt_results=objects,
                query_result=query_result,
                root_prim_path=root_prim_path)
        else:
            place_greyboxes(                    
                gpt_results=objects,
                root_prim_path=root_prim_path)
    else:
        place_greyboxes(                    
            gpt_results=objects,
            root_prim_path=root_prim_path)
    
    task.cancel()
    await asyncio.sleep(1)
    response_label.text = response
    progress_widget.show_bar(False)
