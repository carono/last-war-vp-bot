const gulp = require('gulp');
const concat = require('gulp-concat');
const log = require('fancy-log');
const colors = require('ansi-colors');
const through = require('through2');
const fs = require('fs');
const path = require('path');
const {execSync} = require('child_process');

// Пути
const paths = {
    proc: ['./src/proc/*.lua'],
    classes: ['./src/classes/*.lua'],
};

// Задача для обработки файлов proc — создаёт functions.lua с комментариями
function procTask(options = {}) {
    return (cb) => {
        const {inputPaths = {}, outputDir = './dist'} = options;

        const tasks = Object.entries(inputPaths).map(([key, paths]) => {
            return new Promise((resolve) => {
                gulp.src(paths)
                    .pipe(through.obj((file, _, cb) => {
                        if (file.isBuffer()) {
                            const header = `-- lua ${path.basename(file.path)}\n`;
                            file.contents = Buffer.concat([Buffer.from(header), file.contents]);
                        }
                        cb(null, file);
                    }))
                    .pipe(concat(options.file, {newLine: '\n\n'}))
                    .pipe(gulp.dest(outputDir))
                    .on('end', resolve);
            });
        });

        Promise.all(tasks).then(() => cb());
    };
}

// Задача генерации Classes.lua через require
function generateClassesTask() {
    const classesDir = './src/classes';
    const outputFile = './dist/Classes.lua';

    return gulp.src(path.join(classesDir, '*.lua'))
        .pipe(through.obj(function (file, _, cb) {
            this.files = this.files || [];
            this.files.push(file);
            cb();
        }, function (cb) {
            const lines = this.files.map(file => {
                const filename = path.basename(file.path, '.lua');
                return `require("src.classes.${filename}")`;
            });

            const outputContent = '--lua\n' + lines.join('\n') + '\n';
            fs.mkdirSync(path.dirname(outputFile), {recursive: true});
            fs.writeFileSync(outputFile, outputContent);

            cb();
        }));
}

// Отдельные gulp-задачи
gulp.task('proc', procTask({
    inputPaths: {controllers: paths.proc},
    file: 'functions.lua',
    outputDir: './dist'
}));

gulp.task('classes', generateClassesTask);

// Наблюдение за изменениями
gulp.task('watch', function () {
    gulp.watch(paths.proc, gulp.series('proc'));
    gulp.watch(paths.classes, gulp.series('classes'));
});

// Проверка наличия git
gulp.task('git-check', function (done) {
    try {
        execSync('git --version', {stdio: 'ignore'});
        done();
    } catch (err) {
        console.log(
            colors.red('Git is not installed.'),
            '\n  Git, the version control system, is required to download dependencies.',
            '\n  Download git here:', colors.cyan('http://git-scm.com/downloads') + '.',
            '\n  Once git is installed, run', colors.cyan('npm install'), 'again.'
        );
        process.exit(1);
    }
});

// Задача по умолчанию
gulp.task('default', gulp.series('proc', 'classes'));
