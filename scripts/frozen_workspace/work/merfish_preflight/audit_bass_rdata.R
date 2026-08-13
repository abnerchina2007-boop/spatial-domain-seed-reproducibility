options(stringsAsFactors = FALSE)
load("work/merfish_preflight/bass_official/MERFISH_Animal1.RData")

sections <- c("-0.04", "-0.09", "-0.14", "-0.19", "-0.24")
out_dir <- "work/merfish_preflight"

summaries <- list()
label_rows <- list()
gene_rows <- list()

for (section in sections) {
  x <- cnts_mult[[section]]
  info <- info_mult[[section]]
  labels <- info$z
  finite <- is.finite(x)
  variances <- apply(x, 1, var)
  cell_sums <- colSums(x)
  count_names <- colnames(x)
  info_names <- rownames(info)

  summaries[[section]] <- data.frame(
    section = section,
    n_cells = ncol(x),
    n_genes = nrow(x),
    n_nonzero = sum(x != 0),
    sparsity = 1 - sum(x != 0) / length(x),
    finite = all(finite),
    n_nan_inf = sum(!finite),
    n_negative = sum(x < 0, na.rm = TRUE),
    n_zero_count_cells = sum(cell_sums == 0),
    n_zero_variance_genes = sum(variances == 0 | is.na(variances)),
    all_integer_valued = all(abs(x - round(x)) < 1e-10),
    min_value = min(x, na.rm = TRUE),
    max_value = max(x, na.rm = TRUE),
    min_cell_sum = min(cell_sums),
    median_cell_sum = median(cell_sums),
    max_cell_sum = max(cell_sums),
    unique_gene_names = !anyDuplicated(rownames(x)),
    unique_cell_ids = !anyDuplicated(count_names),
    unique_info_ids = !anyDuplicated(info_names),
    count_info_ids_identical = identical(count_names, info_names),
    coordinates_finite = all(is.finite(info$x)) && all(is.finite(info$y)),
    coordinate_pairs_unique = !anyDuplicated(paste(info$x, info$y, sep = "|")),
    labels_complete = all(!is.na(labels) & nzchar(trimws(labels))),
    n_labels_missing = sum(is.na(labels) | !nzchar(trimws(labels))),
    K_observed = length(unique(labels[!is.na(labels) & nzchar(trimws(labels))])),
    n_ambiguous_other_unknown = sum(tolower(trimws(labels)) %in% c("ambiguous", "other", "unknown"), na.rm = TRUE),
    matrix_memory_bytes = as.numeric(object.size(x)),
    info_memory_bytes = as.numeric(object.size(info)),
    first_count_cell_id = if (length(count_names)) count_names[[1]] else NA_character_,
    first_info_cell_id = if (length(info_names)) info_names[[1]] else NA_character_,
    stringsAsFactors = FALSE
  )

  tab <- as.data.frame(table(labels, useNA = "ifany"), stringsAsFactors = FALSE)
  names(tab) <- c("label", "n_cells")
  tab$section <- section
  label_rows[[section]] <- tab[, c("section", "label", "n_cells")]

  gene_rows[[section]] <- data.frame(
    section = section,
    gene_order = seq_len(nrow(x)),
    gene = rownames(x),
    zero_variance = variances == 0 | is.na(variances),
    stringsAsFactors = FALSE
  )
}

summary_df <- do.call(rbind, summaries)
rownames(summary_df) <- NULL
labels_df <- do.call(rbind, label_rows)
rownames(labels_df) <- NULL
genes_df <- do.call(rbind, gene_rows)
rownames(genes_df) <- NULL

write.csv(summary_df, file.path(out_dir, "section_integrity_audit.csv"), row.names = FALSE)
write.csv(labels_df, file.path(out_dir, "reference_label_counts.csv"), row.names = FALSE)
write.csv(genes_df, file.path(out_dir, "gene_universe_by_section.csv"), row.names = FALSE)

cat("COMMON_GENE_NAMES_IDENTICAL=", all(vapply(sections[-1], function(s) identical(rownames(cnts_mult[[sections[[1]]]]), rownames(cnts_mult[[s]])), logical(1))), "\n", sep = "")
cat("COMMON_GENE_COUNT=", length(rownames(cnts_mult[[sections[[1]]]])), "\n", sep = "")
cat("UNION_LABELS=", paste(sort(unique(unlist(lapply(info_mult[sections], `[[`, "z")))), collapse = "|"), "\n", sep = "")
cat("SUMMARY\n")
print(summary_df, row.names = FALSE)
cat("LABEL_COUNTS\n")
print(labels_df, row.names = FALSE)
cat("GENES\n")
cat(paste(rownames(cnts_mult[[sections[[1]]]]), collapse = "|"), "\n")
