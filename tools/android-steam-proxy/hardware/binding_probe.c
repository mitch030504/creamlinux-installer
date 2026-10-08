/* Inspect the transferred final ELF's dynsym on Android, without LLVM tools. */
#include <elf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include "hardware_symbols.h"

static int within(size_t offset, size_t count, size_t length) {
    return offset <= length && count <= length - offset;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int fd = open(argv[1], O_RDONLY);
    struct stat st;
    if (fd < 0 || fstat(fd, &st) || st.st_size < (off_t)sizeof(Elf64_Ehdr)) return 1;
    size_t length = (size_t)st.st_size;
    const unsigned char *raw = mmap(NULL, length, PROT_READ, MAP_PRIVATE, fd, 0);
    if (raw == MAP_FAILED) return 1;
    const Elf64_Ehdr *eh = (const Elf64_Ehdr *)raw;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) || eh->e_ident[EI_CLASS] != ELFCLASS64 ||
        eh->e_ident[EI_DATA] != ELFDATA2LSB || eh->e_machine != EM_AARCH64 ||
        eh->e_type != ET_DYN || eh->e_shentsize != sizeof(Elf64_Shdr) || !eh->e_shnum ||
        eh->e_shoff % _Alignof(Elf64_Shdr) ||
        !within(eh->e_shoff, (size_t)eh->e_shnum * sizeof(Elf64_Shdr), length)) return 1;
    const Elf64_Shdr *sections = (const Elf64_Shdr *)(raw + eh->e_shoff);
    unsigned seen[HARDWARE_FUNCTION_COUNT] = {0}, global = 0, weak = 0, tables = 0;
    for (unsigned t = 0; t < eh->e_shnum; ++t) {
        const Elf64_Shdr *table = &sections[t];
        if (table->sh_type != SHT_DYNSYM) continue;
        ++tables;
        if (table->sh_link >= eh->e_shnum || table->sh_entsize != sizeof(Elf64_Sym) ||
            table->sh_size % sizeof(Elf64_Sym) || table->sh_offset % _Alignof(Elf64_Sym) ||
            !within(table->sh_offset, table->sh_size, length)) return 1;
        const Elf64_Shdr *strings = &sections[table->sh_link];
        if (strings->sh_type != SHT_STRTAB || !within(strings->sh_offset, strings->sh_size, length)) return 1;
        const Elf64_Sym *symbols = (const Elf64_Sym *)(raw + table->sh_offset);
        for (size_t s = 0; s < table->sh_size / sizeof(Elf64_Sym); ++s) {
            const Elf64_Sym *sym = &symbols[s];
            unsigned binding = ELF64_ST_BIND(sym->st_info), visibility = sym->st_other & 3u;
            if (!sym->st_shndx || binding == STB_LOCAL || (visibility != STV_DEFAULT && visibility != STV_PROTECTED)) continue;
            if (sym->st_name >= strings->sh_size) return 1;
            const char *name = (const char *)(raw + strings->sh_offset + sym->st_name);
            if (!memchr(name, 0, strings->sh_size - sym->st_name)) return 1;
            unsigned i;
            for (i = 0; i < HARDWARE_FUNCTION_COUNT; ++i) if (!strcmp(name, hardware_symbols[i].name)) break;
            if (i == HARDWARE_FUNCTION_COUNT || ++seen[i] != 1 ||
                ELF64_ST_TYPE(sym->st_info) != STT_FUNC || binding != hardware_symbols[i].binding ||
                sym->st_other != hardware_symbols[i].other) {
                fprintf(stderr, "FAIL dynsym: unexpected type/binding/visibility/name %s\n", name); return 1;
            }
            if (binding == STB_WEAK) ++weak; else if (binding == STB_GLOBAL) ++global; else return 1;
        }
    }
    for (unsigned i = 0; i < HARDWARE_FUNCTION_COUNT; ++i) if (seen[i] != 1) return 1;
    if (tables != 1 || global != HARDWARE_GLOBAL_COUNT || weak != HARDWARE_WEAK_COUNT) return 1;
    printf("PASS dynsym: %u GLOBAL, %u WEAK FUNC; exact final-link bindings/visibility\n", global, weak);
    munmap((void *)raw, length);
    close(fd);
    return 0;
}
