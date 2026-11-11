#include "llama.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void fail(const char *message) { fprintf(stderr, "P2TOKENIZER: %s\n", message); exit(2); }
static void write_u32(uint32_t value) { if (fwrite(&value, sizeof(value), 1, stdout) != 1) fail("write length"); }
static void write_bytes(const void *data, size_t size) { if (size && fwrite(data, 1, size, stdout) != size) fail("write bytes"); }

static void encode(const struct llama_vocab *vocab, const char *input, int32_t length, bool add_special) {
    int32_t needed = llama_tokenize(vocab, input, length, NULL, 0, add_special, true);
    if (needed > 0) fail("unexpected successful zero-buffer tokenize");
    needed = -needed;
    if (needed > 1048576) fail("token limit");
    llama_token *tokens = malloc((size_t)(needed + 1) * sizeof(*tokens));
    if (!tokens) fail("allocate tokens");
    int32_t count = llama_tokenize(vocab, input, length, tokens, needed, add_special, true);
    if (count != needed) fail("token count changed");
    write_u32((uint32_t)count);
    write_bytes(tokens, (size_t)count * sizeof(*tokens));
    int32_t text_needed = llama_detokenize(vocab, tokens, count, NULL, 0, false, true);
    if (text_needed > 0) fail("unexpected successful zero-buffer detokenize");
    text_needed = -text_needed;
    if (text_needed > 4194304) fail("decoded-text limit");
    int32_t capacity = text_needed + 256;
    char *decoded = malloc((size_t)capacity);
    if (!decoded) fail("allocate decoded text");
    int32_t actual = llama_detokenize(vocab, tokens, count, decoded, capacity, false, true);
    if (actual < 0) {
        capacity = -actual + 256;
        if (capacity > 4194304) fail("decoded-text retry limit");
        char *larger = realloc(decoded, (size_t)capacity);
        if (!larger) fail("allocate decoded retry");
        decoded = larger;
        actual = llama_detokenize(vocab, tokens, count, decoded, capacity, false, true);
    }
    if (actual < 0 || actual > capacity) fail("detokenized size exceeds buffer");
    write_u32((uint32_t)actual); write_bytes(decoded, (size_t)actual);
    free(decoded); free(tokens);
}

int main(int argc, char **argv) {
    if (argc != 2) fail("usage: native_tokenizer MODEL_GGUF");
    uint32_t endian = 1;
    if (*(unsigned char *)&endian != 1) fail("protocol requires little endian");
    struct llama_model_params params = llama_model_default_params();
    params.n_gpu_layers = 0;
    params.vocab_only = true;
    params.check_tensors = false;
    struct llama_model *model = llama_model_load_from_file(argv[1], params);
    if (!model) fail("vocabulary-only model load failed");
    const struct llama_vocab *vocab = llama_model_get_vocab(model);
    write_bytes("P2TOK01\0", 8);
    write_u32((uint32_t)llama_vocab_n_tokens(vocab));
    write_u32((uint32_t)llama_vocab_bos(vocab));
    write_u32((uint32_t)llama_vocab_eos(vocab));
    write_u32(llama_vocab_get_add_bos(vocab));
    write_u32(llama_vocab_get_add_eos(vocab));
    const char *version = llama_version();
    write_u32((uint32_t)strlen(version)); write_bytes(version, strlen(version));
    fflush(stdout);
    uint32_t length;
    while (fread(&length, sizeof(length), 1, stdin) == 1) {
        if (length > 1048576) fail("prompt transport limit");
        char *input = malloc((size_t)length + 1);
        if (!input) fail("allocate input");
        if (length && fread(input, 1, length, stdin) != length) fail("short input");
        input[length] = '\0';
        encode(vocab, input, (int32_t)length, false);
        encode(vocab, input, (int32_t)length, true);
        free(input); fflush(stdout);
    }
    if (!feof(stdin)) fail("input read failed");
    llama_model_free(model);
    return 0;
}
