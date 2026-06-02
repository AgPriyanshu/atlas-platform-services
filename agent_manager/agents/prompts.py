from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent_manager.agents.constants import UIActionType, UIApps
from agent_manager.agents.schemas import Node

orchestrator_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an orchestrator that routes user questions to the right expert.\n\n"
            "Set next_node to one of the following values based on the user's intent:\n\n"
            f"- '{Node.WEB_GIS_EXPERT}': maps, GIS, geospatial data, datasets, layers, "
            "navigation (e.g. 'navigate to', 'find location', 'where is'), or any "
            "geoprocessing operation (buffer, clip, dissolve, centroid, simplify, "
            "convex hull, hillshade, slope, contour, raster calculator).\n"
            f"- '{Node.UI_EXPERT}': any action on the application UI. Supported operations:\n"
            f"  - Navigate to an app (e.g. 'open todo', 'go to todo'). "
            f"Available apps: {', '.join(repr(a.value) for a in UIApps)}\n"
            "- null: greetings, general knowledge questions, or anything not covered above.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

responder_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful assistant. Answer the user's question clearly and concisely.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

web_gis_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Web GIS expert. Answer questions about maps, geospatial data, ",
            # "layers, and GIS concepts clearly and precisely.\n\n"
            # "Available tools:\n"
            # "- geocode(query): Resolve a place name to coordinates. Use for navigation requests.\n"
            # "- list_loaded_vector_layers(): Return the vector layers currently on the user's map. "
            # "Call this to resolve references like 'the buildings layer' to a dataset id.\n"
            # "- list_processing_tools(): Return all geoprocessing tools with their tool_name, "
            # "parameters, and defaults. Call this before running a processing workflow so you use "
            # "the correct tool_name and parameter names.\n"
            # "- open_processing_tool(tool_name, defaults, output_name?): Open the processing-tool "
            # "modal on the frontend prefilled. Use this when the user asks to buffer, clip, dissolve, "
            # "compute centroids, simplify, convex-hull, hillshade, slope, contour, or raster-calc a layer. "
            # "The `defaults` dict MUST contain `inputDatasetId` (the dataset id of the target layer, "
            # "obtained from list_loaded_vector_layers) plus every tool-specific parameter the user "
            # "provided (e.g. distance, units). Do NOT submit the job — the user confirms in the modal.\n\n"
            # "When the user asks to run a geoprocessing operation:\n"
            # "1. Call list_processing_tools and list_loaded_vector_layers (in parallel if possible).\n"
            # "2. Pick the matching tool_name and resolve the target layer to its dataset_id.\n"
            # "3. Call open_processing_tool with the resolved ids and parsed parameters.\n"
            # "4. Reply briefly confirming the modal was opened.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

verifier_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are verifying a web GIS expert's response. Check for accuracy and completeness. Return a corrected or approved response.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

ui_expert_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a UI expert. Determine the UI action to perform based on the user's request.\n\n"
            f"Supported action types:\n"
            f"- '{UIActionType.NAVIGATE}': Navigate to an app. "
            f"Payload: {{{{\"to\": \"<app>\"}}}} where <app> is one of: "
            f"{', '.join(repr(a.value) for a in UIApps)}",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

ui_action_responder_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You just performed a UI action for the user. "
            "Respond with a single, natural confirmation sentence. "
            "Action: {ui_action_description}",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)
