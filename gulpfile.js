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
    functions: ['./src/functions/*.lua'],
    classes: ['./src/classes/*.lua'],
};

// Задача для обработки файлов proc — создаёт functions.lua с комментариями
function functionsTask(options = {}) {
    const folder = './src/functions';
    const outputFile = './dist/functions.lua';

    return gulp.src(path.join(folder, '*.lua'))
        .pipe(through.obj(function (file, _, cb) {
            this.files = this.files || [];
            this.files.push(file);
            cb();
        }, function (cb) {
            const lines = this.files.map(file => {
                const filename = path.basename(file.path, '.lua');
                return `require("src.functions.${filename}")`;
            });

            const outputContent = '--lua\n' + lines.join('\n') + '\n';
            fs.mkdirSync(path.dirname(outputFile), {recursive: true});
            fs.writeFileSync(outputFile, outputContent);

            cb();
        }));
}

// Задача генерации Classes.lua через require
function classesTask() {
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

gulp.task('functions', functionsTask);
gulp.task('classes', classesTask);

// Наблюдение за изменениями
gulp.task('watch', function () {
    gulp.watch(paths.functions, gulp.series('functions'));
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
gulp.task('default', gulp.series('functions', 'classes'));
