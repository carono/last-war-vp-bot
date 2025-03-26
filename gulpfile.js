const gulp = require('gulp');
const concat = require('gulp-concat');
const log = require('fancy-log');
const colors = require('ansi-colors');
const through = require('through2');
const fs = require('fs');
const path = require('path');
const {execSync} = require('child_process');

const paths = {
    proc: ['./src/proc/*.lua'],
    classes: ['./src/classes/*.lua'],
};

function procTask(options = {}) {
    return (cb) => {
        const {inputPaths = {}, outputDir = './lua'} = options;

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

gulp.task('proc', procTask());

gulp.task('watch', function () {
    gulp.watch(paths.proc, procTask({
        inputPaths: {controllers: paths.proc},
        file: 'functions.lua',
        outputDir: './dist'
    }));

    gulp.watch(paths.classes, procTask({
        inputPaths: {controllers: paths.classes},
        file: 'classes.lua',
        outputDir: './dist'
    }));
});


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

gulp.task('default', gulp.series('proc'));
