#include "llm_client.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DEFAULT_ORCHESTRATOR_URL "http://localhost:5000/process"

const char *get_orchestrator_url() {
  const char *env_url = getenv("ORCHESTRATOR_URL");
  if (env_url)
    return env_url;
  return DEFAULT_ORCHESTRATOR_URL;
}

// Helper to escape special characters for JSON string in shell command
// Very basic escaping for quotes and newlines
void escape_json_string(char *dest, const char *src) {
  int j = 0;
  for (int i = 0; src[i] != '\0'; i++) {
    if (src[i] == '"') {
      dest[j++] = '\\';
      dest[j++] = '"';
    } else if (src[i] == '\\') {
      dest[j++] = '\\';
      dest[j++] = '\\';
    } else if (src[i] == '\'') {
      // Escape single quote for shell: ' -> '\''
      dest[j++] = '\'';
      dest[j++] = '\\';
      dest[j++] = '\'';
      dest[j++] = '\'';
    } else if (src[i] == '\n') {
      dest[j++] = ' ';
    } else {
      dest[j++] = src[i];
    }
  }
  dest[j] = '\0';
}

// Manual JSON parsing to extract "response" field
void extract_response(const char *json_response) {
  const char *key = "\"response\"";
  const char *start = strstr(json_response, key);
  if (!start) {
    printf("[LLM] Could not find response in output.\n");
    return;
  }

  // Move to colon
  start = strchr(start, ':');
  if (!start)
    return;

  // Move to first quote of value
  start = strchr(start, '"');
  if (!start)
    return;
  start++; // Skip opening quote

  printf("[LLM Response]: ");

  // Print until next unescaped quote
  // Note: This is a simple parser and might be fooled by escaped quotes inside
  // the string if not careful. For "response": "...", we just print char by
  // char, handling \"
  int i = 0;
  while (start[i] != '\0') {
    if (start[i] == '"' && (i == 0 || start[i - 1] != '\\')) {
      // End of string
      break;
    }

    // Handle escaped characters for display
    if (start[i] == '\\') {
      i++;
      if (start[i] == 'n')
        printf("\n");
      else if (start[i] == 't')
        printf("\t");
      else if (start[i] == '"')
        printf("\"");
      else
        printf("%c", start[i]); // Print other escaped chars as is
    } else {
      printf("%c", start[i]);
    }
    i++;
  }
  printf("\n");
}

int send_to_llm(const char *prompt) {
  char escaped_prompt[4096]; // Max prompt length
  escape_json_string(escaped_prompt, prompt);

  // Construct curl command hitting the Python FastAPI server
  // The API expects JSON like: {"text": "the prompt"}
  char command[8192];
  snprintf(command, sizeof(command),
           "curl -s -X POST %s -H 'Content-Type: application/json' -d '{\"text\": \"%s\"}'",
           get_orchestrator_url(), escaped_prompt);

  printf("[LLM] Sending query via curl...\n");
  printf("Command: %s\n", command); // Debug

  FILE *fp = popen(command, "r");
  if (fp == NULL) {
    perror("popen failed");
    return -1;
  }

  char buffer[16384]; // Large buffer for response
  size_t bytes_read = fread(buffer, 1, sizeof(buffer) - 1, fp);
  buffer[bytes_read] = '\0';

  pclose(fp);

  if (bytes_read == 0) {
    printf("[LLM] No response from Ollama (is it running?)\n");
    return -1;
  }

  // printf("[LLM] Raw response: %s\n", buffer); // Debug removed per user
  // request
  extract_response(buffer);
  return 0;
}
