from pdf_vox import PDFVox


def main():
    from config import API_KEY, DEFAULT_PDF_PATH, DEFAULT_OUTPUT_DIR

    pdf_vox = PDFVox(API_KEY)

    audio_files = pdf_vox.process(DEFAULT_PDF_PATH, DEFAULT_OUTPUT_DIR)

    print("Generated audio files:")
    for file in audio_files:
        print(f"Page {file['page']}: {file['audio_path']}")


if __name__ == "__main__":
    main()

