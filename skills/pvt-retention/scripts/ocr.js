// OCR local con Vision mediante JXA. No necesita compilación.
// Uso: osascript -l JavaScript ocr.js [--accurate] imagen1.jpg imagen2.jpg
ObjC.import('Foundation');
ObjC.import('Vision');
ObjC.import('AppKit');

function ocr(path, level) {
  const url = $.NSURL.fileURLWithPath($(path));
  const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $());
  const request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = level;
  request.usesLanguageCorrection = true;
  request.recognitionLanguages = $(['es-ES', 'en-US']);
  const error = Ref();
  handler.performRequestsError($([request]), error);
  const results = request.results;
  if (!results || results.count === 0) return '';
  const lines = [];
  for (let i = 0; i < results.count; i++) {
    const candidates = results.objectAtIndex(i).topCandidates(1);
    if (candidates.count > 0) {
      lines.push(ObjC.unwrap(candidates.objectAtIndex(0).string));
    }
  }
  return lines.join('\n');
}

function run(argv) {
  let level = 1;
  if (argv[0] === '--accurate') {
    level = 0;
    argv = argv.slice(1);
  }
  argv.forEach(function (path) {
    let text = '';
    try {
      text = ocr(path, level);
    } catch (error) {
      text = '';
    }
    console.log(JSON.stringify({f: path, t: text}));
  });
  return '';
}
