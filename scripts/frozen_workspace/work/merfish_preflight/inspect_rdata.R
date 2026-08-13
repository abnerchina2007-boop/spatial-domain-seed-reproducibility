load("work/merfish_preflight/bass_official/MERFISH_Animal1.RData")
cat("objects:", paste(ls(), collapse = ", "), "\n")
for (nm in ls()) {
  x <- get(nm)
  cat("\nOBJECT", nm, "class=", paste(class(x), collapse = "/"),
      "size=", format(object.size(x), units = "auto"), "\n")
  if (is.list(x)) {
    cat("names:", paste(names(x), collapse = ", "), "\n")
    cat("length=", length(x), "\n")
  }
  if (!is.null(dim(x))) cat("dim:", paste(dim(x), collapse = "x"), "\n")
  str(x, max.level = 2, vec.len = 8, list.len = 30)
}
