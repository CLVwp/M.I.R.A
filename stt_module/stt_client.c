#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <curl/curl.h>

#define ORCHESTRATOR_URL "http://orchestrator:5000/process"

// Liste de phrases simulées reconnues par le "STT"
const char *mock_sentences[] = {
    "MIRA, s'il te plaît AVANCE de deux mètres.",
    "Quelle est l'autonomie et combien de pattes possède le robot ?",
    "MIRA, SCANNE la zone devant toi.",
    "Peux-tu me rappeler comment initialiser tes servomoteurs ?",
    "MIRA, STOP immédiatement !"
};

void send_post_request(const char *text) {
    CURL *curl;
    CURLcode res;
    
    curl_global_init(CURL_GLOBAL_ALL);
    curl = curl_easy_init();
    
    if(curl) {
        struct curl_slist *headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        
        // Construire le JSON {"text": "..."}
        // Echappement manuel simpliste pour le mock
        char json_payload[512];
        snprintf(json_payload, sizeof(json_payload), "{\"text\": \"%s\"}", text);

        curl_easy_setopt(curl, CURLOPT_URL, ORCHESTRATOR_URL);
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_payload);
        
        printf("[STT C-Client] Sending recognized speech to M.I.R.A Orchestrator: '%s'\n", text);
        
        // Exécuter la requête
        res = curl_easy_perform(curl);
        
        if(res != CURLE_OK) {
            fprintf(stderr, "[STT C-Client] curl_easy_perform() failed: %s\n", curl_easy_strerror(res));
        } else {
            printf("\n[STT C-Client] Message successfully routed.\n\n");
        }
        
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }
    curl_global_cleanup();
}

int main(void) {
    int num_sentences = sizeof(mock_sentences) / sizeof(mock_sentences[0]);
    int index = 0;
    
    printf("Starting M.I.R.A STT Mock Module...\n");
    printf("Connecting to Orchestrator at %s\n", ORCHESTRATOR_URL);
    
    // Boucle infinie qui simule une reconnaissance vocale toutes les 10 secondes
    while (1) {
        // Attendre 10 secondes entre chaque "reconnaissance vocale"
        sleep(10);
        
        const char *recognized_text = mock_sentences[index];
        send_post_request(recognized_text);
        
        index = (index + 1) % num_sentences;
    }
    
    return 0;
}
