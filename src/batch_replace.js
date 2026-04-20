const fs = require('fs');
const path = require('path');

const replacements = {
  "gemini-2.5-flash": "gemini-2.5-flash",
  "gemini-2.5-flash": "gemini-2.5-flash",
  "gemini-2.5-pro": "gemini-2.5-pro",
  "gemini-2.5-pro": "gemini-2.5-pro",
  "gemini-2.5-flash": "gemini-2.5-flash",
  "gemini-2.5-flash": "gemini-2.5-flash",
  "MODEL_GEMINI": "MODEL_GEMINI",
  "MODEL_GEMINI_PRO": "MODEL_GEMINI_PRO",
  "MODEL_GEMINI_FLASH": "MODEL_GEMINI_FLASH",
  "MODEL_GEMINI": "MODEL_GEMINI",
  "GEMINI_MODEL": "GEMINI_MODEL",
  "GEMINI_API_KEY": "GEMINI_API_KEY"
};

const exts = ['.py', '.yaml', '.yml', '.js', '.html', '.md'];

function walkSync(currentDirPath, callback) {
    fs.readdirSync(currentDirPath).forEach(function (name) {
        var filePath = path.join(currentDirPath, name);
        var stat = fs.statSync(filePath);
        if (stat.isFile()) {
            callback(filePath, stat);
        } else if (stat.isDirectory()) {
            // skip executions and logs
            if (name === 'executions' || name === 'logs' || name === '.git' || name === 'node_modules' || name === '.venv') return;
            walkSync(filePath, callback);
        }
    });
}

const targetDir = 'r:/Github/koya/src';

walkSync(targetDir, function(filePath, stat) {
    const ext = path.extname(filePath);
    const basename = path.basename(filePath);
    
    let isTarget = false;
    if (exts.includes(ext)) {
        isTarget = true;
    } else if (basename.startsWith('.env')) {
        isTarget = true;
    }
    
    if (isTarget) {
        let content = fs.readFileSync(filePath, 'utf8');
        let newContent = content;
        for (const [oldStr, newStr] of Object.entries(replacements)) {
            newContent = newContent.split(oldStr).join(newStr);
        }
        if (content !== newContent) {
            fs.writeFileSync(filePath, newContent, 'utf8');
            console.log(`Updated: ${filePath}`);
        }
    }
});
