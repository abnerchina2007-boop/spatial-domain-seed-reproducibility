suppressPackageStartupMessages(library(Matrix))
load("work/merfish_preflight/bass_official/MERFISH_Animal1.RData")

sections <- c("-0.04", "-0.09", "-0.14", "-0.19", "-0.24")
root <- "work/merfish_preflight/exported_sections"
dir.create(root, recursive = TRUE, showWarnings = FALSE)

for (section in sections) {
  section_id <- paste0("MERFISH_Bregma_m", sub("^-", "", section))
  out <- file.path(root, section_id)
  dir.create(out, recursive = TRUE, showWarnings = FALSE)
  x <- cnts_mult[[section]]
  info <- info_mult[[section]]
  stopifnot(identical(colnames(x), rownames(info)))
  stopifnot(identical(rownames(x), rownames(cnts_mult[[sections[[1]]]])))
  stopifnot(nrow(x) == 155L, length(unique(info$z)) == 8L)

  # Matrix Market is observations x genes for direct AnnData import.
  writeMM(as(t(x), "dgCMatrix"), file.path(out, "expression_normalized.mtx"))
  write.table(
    data.frame(cell_id = colnames(x), x = info$x, y = info$y,
               reference_domain = info$z, cell_class = info$Cell_class,
               neuron_cluster_id = info$Neuron_cluster_ID,
               stringsAsFactors = FALSE),
    file.path(out, "cells.tsv"), sep = "\t", row.names = FALSE, quote = FALSE,
    na = ""
  )
  write.table(
    data.frame(gene = rownames(x), stringsAsFactors = FALSE),
    file.path(out, "genes.tsv"), sep = "\t", row.names = FALSE, quote = FALSE
  )
}
